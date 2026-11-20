# -*- coding: utf-8 -*-
"""expressive_tts.py — 表达力配音：重点放慢加重、逐字强调、多音字定音。

与 clone_tts.py 同源（F5-TTS 声线克隆），但按"配音导演"逻辑把每幕读白
切成片段，分别合成再拼接：
  n = 正常（base 语速，音量 1.0）
  k = 重点（语速 ×0.85，音量 +32%——结论/答案/关键数字）
  s = 逐字（字间加顿号，语速 ×0.7，音量 +20%——极重要的短语）

多音字：内置"卷=4声(试卷义)"等教学场景规则；配置 AI Key 后由 AI 按上下文
定音，用同音字替换强制读音（只替换合成文本，字幕/稿件保留原文）。

用法：
  python expressive_tts.py 分镜.md audio --ref 声线.wav [--base-speed 0.85]
      [--ai-key K --ai-base B --ai-model M] [--format mp3]
输出：audio/*.mp3 + audio_info.json + timeline.json（与 validate_audio 兼容）
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clone_tts import (Cloner, get_ffmpeg, get_ref_text, parse_md_table,
                       read_duration, transcode)

# ---------------- 多音字规则（合成文本替换；字幕原文不受影响） ----------------
POLY_RULES = [
    ("试卷", "试倦"), ("卷子", "倦子"), ("答卷", "答倦"), ("一卷", "一倦"),
    ("刷卷", "刷倦"), ("考试卷", "考试倦"), ("卷面上", "倦面上"),
    ("这条卷", "这条倦"), ("成绩卷", "成绩倦"),
]


def apply_poly(text):
    for a, b in POLY_RULES:
        text = text.replace(a, b)
    return text


# ---------------- 逐字稿内嵌标记（**重点** / !!逐字!! / [停x] / [音:…=…]） ----------------

MARKUP_SPLIT_RE = re.compile(
    r"(\*\*.+?\*\*|!!.+?!!|\[停\d+(?:\.\d+)?\]|\[音:[^\]=]+=[^\]]+\])")
STOP_RE = re.compile(r"\[停(\d+(?:\.\d+)?)\]")
PRON_RE = re.compile(r"\[音:([^=\]]+)=([^\]]+)\]")


def has_markup(narr):
    return bool(MARKUP_SPLIT_RE.search(narr))


def markup_annotate(narr):
    """带标记的读白 → 分段。[停x] 生成静音段，[音:A=B] 声明本幕发音替换规则。"""
    rules = PRON_RE.findall(narr)          # 先取规则
    narr = PRON_RE.sub("", narr)           # 再删标记（避免规则字面被污染）
    for a, b in rules:                     # 最后对剩余文本做同音字替换
        narr = narr.replace(a, b)
    segs = []
    for p in MARKUP_SPLIT_RE.split(narr):
        if not p or not p.strip():
            continue
        m = STOP_RE.fullmatch(p.strip())
        if m:
            segs.append({"sil": float(m.group(1))})
        elif p.startswith("**") and p.endswith("**") and p[2:-2].strip():
            segs.append({"t": p[2:-2].strip(), "st": "k"})
        elif p.startswith("!!") and p.endswith("!!") and p[2:-2].strip():
            segs.append({"t": p[2:-2].strip(), "st": "s"})
        else:
            clean = p.strip()
            if clean:
                segs.append({"t": clean, "st": "n"})
    # 纯标点的 n 段并入前一段（避免孤立的「。」单独合成）
    merged = []
    for seg in segs:
        if ("t" in seg and seg.get("st") == "n"
                and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", seg["t"])
                and merged and "t" in merged[-1]):
            merged[-1]["t"] += seg["t"]
        else:
            merged.append(seg)
    return merged or [{"t": narr, "st": "n"}]


# ---------------- 分段标注（无 AI：规则引擎） ----------------
KEY_WORDS = re.compile(
    r"答案|结论|记住|切记|关键|注意|一定要|千万别|易错|错在|最重要|"
    r"所以|因此|等于|＞|＜|＞|填|选|就填|＝")


def heuristic_annotate(narr):
    """按句切分 → 关键句标 k、超短答案句标 s、其余 n；长句在逗号处再切。"""
    sents = [s for s in re.split(r"(?<=[。！？；!?;])", narr) if s.strip()]
    segs = []
    for sent in sents:
        pieces = re.split(r"(?<=[，,、：:])", sent)
        pieces = [p for p in pieces if p.strip()]
        if not pieces:
            pieces = [sent]
        is_key = bool(KEY_WORDS.search(sent))
        for p in pieces:
            clean = p.strip()
            if not clean:
                continue
            if len(clean) <= 12 and re.search(r"答案|选|填|＝|=", clean):
                segs.append({"t": clean, "st": "s"})
            elif is_key or KEY_WORDS.search(clean):
                segs.append({"t": clean, "st": "k"})
            else:
                segs.append({"t": clean, "st": "n"})
    return segs or [{"t": narr, "st": "n"}]


# ---------------- 分段标注（AI：配音导演） ----------------
AI_DIRECTOR = (
    "你是配音导演。把每段教学读白切成 5~22 字的片段，逐段标注朗诵风格："
    "n=正常；k=重点（讲结论/答案/关键数字/易错点时，放慢并加重）；"
    "s=逐字强调（极重要、需要一字一顿的短语，如最终答案、关键口诀）。"
    "同时处理多音字：按上下文选择正确读音；若常用读音可能被 TTS 误读，"
    "用同音字替换该字（例如「卷」在试卷/卷子义读第四声 juàn，替换为「倦」），"
    "只改写合成文本，不改变词义。"
    '严格输出 JSON：{"segs": [[{"t":"片段","st":"n|k|s"}, ...], ...]}，'
    "segs 数组与输入的 narrs 一一对应，不要输出其他文字。"
)


def ai_annotate_all(cfg, narrs):
    body = {"narrs": [n[:800] for n in narrs]}
    url = cfg["ai_base"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url, data=json.dumps({
            "model": cfg["ai_model"],
            "messages": [{"role": "system", "content": AI_DIRECTOR},
                         {"role": "user", "content": json.dumps(body, ensure_ascii=False)}],
            "temperature": 0.2}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['ai_key']}"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        out = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", out, re.S)
    data = json.loads(m.group(0))
    segs = data["segs"]
    assert isinstance(segs, list) and len(segs) == len(narrs)
    for arr in segs:
        for s in arr:
            assert s.get("t") and s.get("st") in ("n", "k", "s")
    return segs


# ---------------- 片段合成与拼接 ----------------
STYLE_SPEED = {"n": 1.0, "k": 0.85, "s": 0.7}
STYLE_VOL = {"n": 1.0, "k": 1.32, "s": 1.2}


def spell_text(t):
    chars = [ch for ch in t if re.match(r"[\u4e00-\u9fffA-Za-z0-9]", ch)]
    return "、".join(chars) if chars else t


def synth_segments(cloner, ref, ref_text, segs, base_speed, tmpdir):
    """逐段合成，返回 (wav 路径列表, 音量列表)。含静音段（{"sil": 秒}）。"""
    files, vols = [], []
    ff = get_ffmpeg()
    for j, seg in enumerate(segs):
        if seg.get("sil"):
            out = tmpdir / f"seg_{j:03d}_sil.wav"
            subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                            "-t", str(seg["sil"]), str(out)],
                           check=True, capture_output=True)
            files.append(out)
            vols.append(1.0)
            continue
        st = seg.get("st", "n")
        text = apply_poly(seg["t"])
        if st == "s":
            text = spell_text(text)
        speed = base_speed * STYLE_SPEED[st]
        out = tmpdir / f"seg_{j:03d}.wav"
        cloner.synth(ref, ref_text, text, str(out), speed=speed)
        files.append(out)
        vols.append(STYLE_VOL[st])
    return files, vols


def concat_volume(ff, files, vols, out_wav):
    """按片段音量合成（volume 滤镜 + concat）。"""
    n = len(files)
    if n == 1:
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(files[0]), "-af", f"volume={vols[0]}", str(out_wav)]
        subprocess.run(cmd, check=True, capture_output=True)
        return
    inputs, fc_parts, concat = [], [], ""
    for i, (f, v) in enumerate(zip(files, vols)):
        inputs += ["-i", str(f)]
        fc_parts.append(f"[{i}:a]volume={v},aresample=24000,aformat=channel_layouts=mono[a{i}]")
        concat += f"[a{i}]"
    fc = ";".join(fc_parts) + f";{concat}concat=n={n}:v=0:a=1[out]"
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"] + inputs + \
          ["-filter_complex", fc, "-map", "[out]", str(out_wav)]
    subprocess.run(cmd, check=True, capture_output=True)


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("outdir")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--base-speed", type=float, default=0.85)
    ap.add_argument("--format", default="mp3", choices=["mp3", "wav"])
    ap.add_argument("--ai-key", default="")
    ap.add_argument("--ai-base", default="https://api.deepseek.com/v1")
    ap.add_argument("--ai-model", default="deepseek-chat")
    args = ap.parse_args()

    board, outdir = Path(args.board), Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    entries = parse_md_table(board)
    if not entries:
        print("[错误] 分镜表中没有音频条目")
        return 1
    ff = get_ffmpeg()
    assert ff, "找不到 ffmpeg"

    ref = Path(args.ref)
    cloner = Cloner.get()
    ref_text = get_ref_text(ref, ref.parent, "cuda" if os.environ.get("CUDA_OK", "1") else "cpu")

    narrs = [tx for _, tx in entries]
    marked = [has_markup(n) for n in narrs]
    segs_all = None
    if args.ai_key and not all(marked):
        try:
            print("[AI] 配音导演标注中…")
            segs_all = ai_annotate_all(
                {"ai_base": args.ai_base, "ai_key": args.ai_key,
                 "ai_model": args.ai_model}, narrs)
            print(f"[AI] 标注完成（{len(segs_all)} 幕）")
        except Exception as e:
            print(f"[警告] AI 标注失败（{e}），退回规则引擎")
    if segs_all is None:
        segs_all = [heuristic_annotate(n) for n in narrs]
        print("[规则] 使用启发式分段标注")
    # 带内嵌标记的读白按标记分段（标记优先级最高）
    n_marked = 0
    for i, mk in enumerate(marked):
        if mk:
            segs_all[i] = markup_annotate(narrs[i])
            n_marked += 1
    if n_marked:
        print(f"[标记] {n_marked} 幕读白含逐字稿标记（**重点**/!!逐字!!/[停]/[音:]），按标记分段")

    tmpdir = Path(tempfile.mkdtemp(prefix="expr_tts_"))
    results, total, t_start = [], 0.0, time.time()
    try:
        for i, ((raw_name, text), segs) in enumerate(zip(entries, segs_all), 1):
            name = Path(raw_name).name
            if not name.lower().endswith((".mp3", ".wav")):
                name += "." + args.format
            final_path = outdir / name
            t0 = time.time()
            try:
                files, vols = synth_segments(cloner, str(ref), ref_text,
                                             segs, args.base_speed, tmpdir)
                scene_wav = tmpdir / f"scene_{i:03d}.wav"
                concat_volume(ff, files, vols, scene_wav)
                if final_path.suffix.lower() == ".wav":
                    shutil.copy2(scene_wav, final_path)
                elif not transcode(scene_wav, final_path, args.format):
                    shutil.copy2(scene_wav, final_path)
                dur = read_duration(final_path)
                results.append({"scene": i, "file": name, "text": text,
                                "duration": round(dur, 3)})
                total += dur
                print(f"[{i}/{len(entries)}] {name}  {dur:.2f}s  "
                      f"({len(segs)} 段，{time.time()-t0:.1f}s)")
            except Exception as e:
                print(f"[{i}/{len(entries)}] [失败] {e}")
                continue
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    (outdir / "audio_info.json").write_text(
        json.dumps({"files": results, "total_duration": round(total, 3),
                    "count": len(results), "engine": "F5-TTS-expressive",
                    "ref_audio": Path(args.ref).name,
                    "speed": args.base_speed},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"成功 {len(results)}/{len(entries)}，总时长 {total:.2f}s "
          f"({total/60:.2f} 分钟)，耗时 {time.time()-t_start:.1f}s")
    print(f"已写出 {outdir / 'audio_info.json'}")
    print("=" * 60)
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
TTS 音频生成（Edge TTS）

上游版本的问题与本版修复：
  1. 上游把 edge-tts 的输出直接写成 .wav，但 edge-tts 实际产出的是 MP3 数据。
     文件头与扩展名不符，导致 wave 模块读时长必然失败、Manim 加载也可能异常。
     本版：统一输出 .mp3，并在需要 wav 时用 ffmpeg 真正转码。
  2. 上游 read_duration 用 try/except 静默吞掉异常，最终只返回 0，
     错误信息完全丢失。本版：显式报错并指出回退路径。
  3. 上游情感列（热情/平和）在语音映射里根本没对应实现，属于文档承诺但代码未兑现。
     本版：明确忽略该列并说明，避免误以为生效。

用法：
    python generate_tts.py audio_list.csv ./audio --voice xiaoxiao
    python generate_tts.py 分镜.md ./audio            # 直接从 md 的音频清单表生成
    python generate_tts.py audio_list.csv ./audio --format wav
"""

import argparse
import asyncio
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 数学表达式 -> 中文读白（分数语序、符号读法）
sys.path.insert(0, str(Path(__file__).parent))
from math_speech import convert_math  # noqa: E402

VOICE_MAP = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "xiaoyi": "zh-CN-XiaoyiNeural",
    "yunyang": "zh-CN-YunyangNeural",
    "yunjian": "zh-CN-YunjianNeural",
    "yunxi": "zh-CN-YunxiNeural",
    "yunxia": "zh-CN-YunxiaNeural",
    "yunjhe": "zh-CN-YunjheNeural",
}

# 表达力标记（expressive_tts 专用语法）在机器音色下转纯文本：
#   **重点** / !!逐字!! → 保留内文；[停0.8] → 逗号（自然停顿）；[音:卷=倦] → 倦（修正发音）
RE_MARKUP = re.compile(r"\*\*|!!")
RE_PAUSE = re.compile(r"\[停\d+(?:\.\d+)?\]")
RE_PRON = re.compile(r"\[音:[^\]=]+=([^\]]+)\]")


def clean_markup(text: str) -> str:
    text = RE_PRON.sub(r"\1", text)
    text = RE_PAUSE.sub("，", text)
    text = RE_MARKUP.sub("", text)
    text = re.sub(r"(?<=[。！？；：])，", "", text)          # 「。，」→「。」
    text = re.sub(r"([，。！？；：])\1+", r"\1", text)      # 重叠标点合并
    return text.strip()


def get_ffmpeg():
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    p = shutil.which(exe)
    if p:
        return p
    try:
        import imageio_ffmpeg

        b = imageio_ffmpeg.get_ffmpeg_exe()
        return b if b and Path(b).exists() else None
    except Exception:
        return None


def read_duration(path: Path) -> float:
    """读音频时长（秒）。三级回退，任何一级失败都给出可见提示。"""
    # 1) mutagen —— 对 mp3/wav/m4a 通用，最可靠
    try:
        from mutagen import File as MFile

        m = MFile(str(path))
        if m is not None and getattr(m, "info", None) and m.info.length:
            return float(m.info.length)
    except Exception as e:
        print(f"    [debug] mutagen 读取失败: {e}")

    # 2) wave —— 仅真正 WAV 可用
    try:
        import wave

        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception as e:
        print(f"    [debug] wave 读取失败: {e}")

    # 3) pydub（依赖 ffmpeg）
    try:
        from pydub import AudioSegment

        return len(AudioSegment.from_file(str(path))) / 1000.0
    except Exception as e:
        print(f"    [debug] pydub 读取失败: {e}")

    print(f"    [警告] 无法读取 {path.name} 的时长，请用 ffmpeg 确认文件")
    return 0.0


def parse_csv(path: Path):
    entries = []
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                sample = f.read(2048)
                f.seek(0)
                delim = ";" if sample.count(";") > sample.count(",") else ","
                for row in csv.DictReader(f, delimiter=delim):
                    fn = row.get("filename") or row.get("文件名") or row.get("file")
                    tx = (
                        row.get("text")
                        or row.get("对白")
                        or row.get("content")
                        or row.get("读白")
                        or row.get("文本")
                    )
                    if fn and tx:
                        entries.append((fn.strip(), tx.strip()))
            return entries
        except UnicodeDecodeError:
            continue
    return entries


def parse_md_table(path: Path):
    """直接从分镜 md 的「音频生成清单」表格提取文件名与读白。"""
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        fn = tx = None
        for c in cells:
            m = re.search(r"(audio_\d+[^|\s]*\.(?:wav|mp3))", c)
            if m:
                fn = m.group(1)
                break
        if not fn:
            continue
        for c in cells:
            if c.startswith(("'", "“", '"')) and len(c) > 4:
                tx = c.strip("'’“”\" ")
                break
        if tx:
            entries.append((fn, tx))
    return entries


def convert_to_wav(src: Path, dst: Path):
    ff = get_ffmpeg()
    if not ff:
        print(f"    [警告] 无 ffmpeg，跳过转码，保留 {src.suffix}")
        return None
    r = subprocess.run(
        [ff, "-y", "-i", str(src), "-ar", "44100", "-ac", "1", str(dst)],
        capture_output=True,
    )
    return dst if r.returncode == 0 and dst.exists() else None


async def synth_one(text, out_path: Path, voice_id):
    import edge_tts

    comm = edge_tts.Communicate(text, voice_id)
    await comm.save(str(out_path))
    return out_path.exists() and out_path.stat().st_size > 0


async def run(args):
    try:
        import edge_tts
    except ImportError:
        print("[错误] edge-tts 未安装: pip install edge-tts")
        return 1

    src = Path(args.input)
    if not src.exists():
        print(f"[错误] 找不到输入文件: {src}")
        return 1

    entries = parse_md_table(src) if src.suffix.lower() == ".md" else parse_csv(src)
    if not entries:
        print("[错误] 未解析到任何 (文件名, 文本) 对")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    voice_id = VOICE_MAP.get(args.voice, VOICE_MAP["xiaoxiao"])

    print("=" * 56)
    print(f"TTS 生成  语音={voice_id}  条目={len(entries)}  输出={outdir}")
    print("=" * 56)

    results = []
    for i, (raw_name, text) in enumerate(entries, 1):
        name = Path(raw_name).name
        if not name.lower().endswith((".mp3", ".wav")):
            name += ".mp3"

        stem = Path(name).stem
        final_ext = ".wav" if args.format == "wav" else ".mp3"
        final_name = stem + final_ext
        final_path = outdir / final_name

        print(f"[{i}/{len(entries)}] {final_name}")
        print(f"原文: {text[:60]}{'...' if len(text) > 60 else ''}")
        speech = text if args.raw else convert_math(clean_markup(text))
        if speech != text:
            print(f"读白: {speech[:60]}{'...' if len(speech) > 60 else ''}")

        tmp = outdir / ("__tmp_" + stem + ".mp3")
        try:
            ok = await synth_one(speech, tmp, voice_id)
        except Exception as e:
            print(f"    [失败] {e}")
            ok = False

        if not ok:
            print("    [失败] 跳过")
            continue

        if args.format == "wav":
            got = convert_to_wav(tmp, final_path)
            if got is None:
                got = tmp
                final_path = tmp
            else:
                tmp.unlink(missing_ok=True)
        else:
            tmp.replace(outdir / final_name)

        dur = read_duration(final_path)
        m = re.search(r"(\d+)", stem)
        results.append(
            {
                "scene": int(m.group()) if m else i,
                "file": final_path.name,
                "text": text,
                "duration": round(dur, 3),
            }
        )
        print(f"    [OK] {dur:.2f}s")

    if not results:
        print("[失败] 没有成功生成任何音频")
        return 1

    total = sum(r["duration"] for r in results)
    info = {
        "files": results,
        "total_duration": round(total, 3),
        "count": len(results),
        "voice": args.voice,
    }
    (outdir / "audio_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("-" * 56)
    print(f"成功 {len(results)}/{len(entries)}，总时长 {total:.2f}s ({total/60:.2f} 分钟)")
    print(f"已写出 {outdir / 'audio_info.json'}")
    return 0 if len(results) == len(entries) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="CSV 或 分镜.md")
    ap.add_argument("outdir", nargs="?", default="./audio")
    ap.add_argument("--voice", default="xiaoxiao")
    ap.add_argument("--format", choices=["mp3", "wav"], default="mp3")
    ap.add_argument("--raw", action="store_true",
                    help="不做数学式转读白（默认会转换：11/4 -> 四分之十一）")
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
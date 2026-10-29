#!/usr/bin/env python3
"""
音频验证与分镜时长回填  （补齐上游仓库缺失的脚本）

功能：
1. 读取 audio/audio_info.json 获取每段音频的真实时长
2. 校验音频文件存在、时长 > 0、与分镜幕数一致
3. 把真实时长回填进「音频生成清单」表格的时长列
4. 额外产出 timeline.json 供 Manim 场景直接加载

兼容：
- 时长列可能为空、可能写着「8 秒」「约15s」「待定」等占位文本，一律覆盖
- 分镜表支持 markdown 表格，也支持 CSV

使用：
    python validate_audio.py 分镜.md ./audio
    python validate_audio.py 分镜.md ./audio --json-only
"""

import sys
import json
import re
from pathlib import Path

DURATION_PLACEHOLDER = re.compile(
    r"^\s*(?:-|—|~|约)?\s*\d+(?:\.\d+)?\s*(?:秒|s|sec|secs|seconds)?\s*(?:-|—|~|约)?\s*$"
)


def load_audio_info(audio_dir: Path):
    """读取 audio_info.json，兼容缺失与多种字段命名。"""
    for name in ("audio_info.json", "audio_manifest.json", "timeline.json"):
        p = audio_dir / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")), p.name
            except json.JSONDecodeError as e:
                print(f"[警告] {name} 解析失败: {e}")
    return None, None


def normalize_entries(info):
    """把不同来源的 json 统一成 [(scene, file, duration), ...]"""
    out = []
    if not info:
        return out
    for item in info.get("files") or info.get("scenes") or info.get("segments") or []:
        if not isinstance(item, dict):
            continue
        scene = item.get("scene", item.get("index", item.get("i", 0)))
        fname = item.get("file", item.get("filename", item.get("audio", "")))
        dur = item.get("duration", item.get("dur", 0)) or 0
        try:
            out.append((int(scene), str(fname), float(dur)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def scan_audio_dir(audio_dir: Path):
    """兜底：直接扫描目录里的音频，用 mutagen/wave 读时长。"""
    results = []
    files = sorted(
        [p for p in audio_dir.iterdir()
         if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg") and not p.name.startswith(".")],
        key=lambda p: p.name,
    )
    for idx, p in enumerate(files, 1):
        m = re.search(r"(\d+)", p.stem)
        scene = int(m.group()) if m else idx
        results.append((scene, p.name, read_duration(p)))
    return results


def read_duration(path: Path) -> float:
    """读取音频时长（秒），失败返回 0.0。"""
    try:
        from mutagen import File as MFile
        m = MFile(str(path))
        if m is not None and getattr(m, "info", None) and m.info.length:
            return float(m.info.length)
    except Exception:
        pass
    try:
        import wave
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception:
        pass
    try:
        from pydub import AudioSegment
        return len(AudioSegment.from_file(str(path))) / 1000.0
    except Exception:
        pass
    return 0.0


def parse_storyboard_scenes(md_text):
    """从分镜 md 中解析出幕号列表，兼容「### 第1幕：xxx」和表格行。"""
    scenes = []
    for m in re.finditer(r"#{2,4}\s*第\s*(\d+)\s*[幕章]", md_text):
        scenes.append(int(m.group(1)))
    if not scenes:
        for line in md_text.splitlines():
            if line.strip().startswith("|") and re.search(r"audio_\d+", line):
                m = re.search(r"(\d+)", line)
                if m:
                    scenes.append(int(m.group(1)))
    return sorted(set(scenes))


def fill_table(md_text, entries):
    """把时长回填进 markdown 表格的行内。返回 (新文本, 回填条数)。"""
    lookup = {e[1]: e[2] for e in entries}
    lines = md_text.splitlines()
    filled = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue

        hit = None
        for c in cells:
            m = re.search(r"(audio_\d+[^|\s]*\.(?:wav|mp3))", c)
            if m:
                hit = m.group(1)
                break
        if not hit:
            continue

        dur = lookup.get(hit)
        if dur is None:
            for s, f, d in entries:
                if s in f or f.split("_")[1:2] == hit.split("_")[1:2]:
                    dur = d
                    break
        if dur is None:
            continue

        for j, c in enumerate(cells):
            if re.match(r"^\d+(\.\d+)?$", c.replace(" ", "")):
                cells[j] = f"{dur:.2f}s"
                filled += 1
                break
        else:
            for j, c in enumerate(cells):
                if DURATION_PLACEHOLDER.match(c) or c in ("", "-", "—", "待定", "TBD"):
                    if j == len(cells) - 1:
                        cells[j] = f"{dur:.2f}s"
                    else:
                        cells.insert(j + 1, f"{dur:.2f}s")
                    filled += 1
                    break
        lines[i] = "| " + " | ".join(cells) + " |"

    return "\n".join(lines), filled


def fill_inline(md_text, entries):
    """回填「第一幕（15 秒）」这类写在标题里的预估时长。"""
    lookup = {e[1]: e[2] for e in entries}
    order = {e[0]: e[2] for e in entries}
    n = 0

    def title_repl(m):
        nonlocal n
        num = int(m.group(1))
        dur = order.get(num)
        if dur is None:
            return m.group(0)
        n += 1
        return f"{m.group(2)}{num}{m.group(3)}（{dur:.1f} 秒）"

    md_text = re.sub(
        r"(#{2,4}\s*第\s*)(\d+)(\s*[幕章][^\n（(]*)[（(]\s*\d+(?:\.\d+)?\s*(?:秒|s|sec)?\s*[）)]",
        title_repl,
        md_text,
    )
    return md_text, n


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if not args:
        print("用法: python validate_audio.py <分镜.md> [音频目录] [--json-only]")
        sys.exit(1)

    board = Path(args[0])
    audio_dir = Path(args[1]) if len(args) > 1 else Path("audio")

    if not board.exists():
        print(f"[错误] 找不到分镜文件: {board}")
        sys.exit(1)
    if not audio_dir.is_dir():
        print(f"[错误] 找不到音频目录: {audio_dir}")
        sys.exit(1)

    info, src = load_audio_info(audio_dir)
    entries = normalize_entries(info)

    missing_meta = entries == []
    if missing_meta:
        entries = scan_audio_dir(audio_dir)
        print("[提示] 未找到 audio_info.json，改为直接扫描音频目录")

    if not entries:
        print(f"[错误] {audio_dir} 下没有可用音频")
        sys.exit(1)

    print("=" * 56)
    print(f"音频验证  来源: {src or '目录扫描'}")
    print("=" * 56)

    problems = []
    total = 0.0
    for scene, fname, dur in entries:
        path = audio_dir / fname
        exists = path.exists()
        if not exists:
            problems.append(f"缺少第 {scene} 幕音频: {fname}")
        if dur <= 0:
            real = read_duration(path) if exists else 0.0
            if real > 0:
                dur = real
                entries[[e[1] for e in entries].index(fname)] = (scene, fname, real)
            else:
                problems.append(f"第 {scene} 幕时长异常，请检查格式: {fname}")
        total += dur
        flag = "OK" if (exists and dur > 0) else "FAIL"
        print(f"  [{flag}] 幕 {scene:>2}  {fname:<40} {dur:>7.2f}s")

    md_text = board.read_text(encoding="utf-8")
    board_scenes = parse_storyboard_scenes(md_text)
    if board_scenes and len(board_scenes) != len(entries):
        problems.append(f"幕数不匹配：分镜 {len(board_scenes)} 幕，音频 {len(entries)} 个")

    print("-" * 56)
    print(f"  共 {len(entries)} 段，总时长 {total:.2f}s ({total/60:.1f} 分钟)")

    filled = 0
    if "--json-only" not in flags and board_scenes:
        md_text, filled = fill_table(md_text, entries)
        md_text, n2 = fill_inline(md_text, entries)
        filled += n2
        board.write_text(md_text, encoding="utf-8")
        print(f"  已回填时长到分镜: {board}（{filled} 处）")

    timeline = {
        "scenes": [
            {"index": s, "file": f, "duration": round(d, 3)}
            for s, f, d in entries
        ],
        "total_duration": round(total, 3),
        "count": len(entries),
    }
    (audio_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  已写出: {audio_dir / 'timeline.json'}")

    if problems:
        print("=" * 56)
        print("[验证失败]")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    print("=" * 56)
    print("[验证通过]")


if __name__ == "__main__":
    main()
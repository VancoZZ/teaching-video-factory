#!/usr/bin/env python3
"""
声线克隆配音（F5-TTS，本地 GPU）

用一段参考音频克隆音色，把分镜里的读白文本合成成你自己的声音。
与 generate_tts.py（edge-tts，云端）并列使用，接口保持一致。

为什么选 F5-TTS：
  · 纯 pip 可装，Windows 无需编译，MIT 协议可商用
  · 3 秒参考音频即可零样本克隆，不需要训练
  · 中英双语，数学读白够用；RTX 4060 上约 3-4 秒生成一句

用法：
    # 从分镜 md 生成（与 edge-tts 完全同构）
    python clone_tts.py 分镜.md ./audio --ref 声线参考/clean_24k.wav

    # 单句试听
    python clone_tts.py --text "各位同学好" --ref 声线参考/clean_24k.wav -o test.wav

    # 批量 CSV
    python clone_tts.py list.csv ./audio --ref 声线参考/clean_24k.wav

参考音频要求：
    15-30 秒最佳，≥6 秒可用。预处理用 prep_voice.py（去静音+归一化）。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 必须清掉外部注入的 PYTHONPATH，否则 f5_tts 可能被错误路径的同名包顶替
for _k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
    os.environ.pop(_k, None)

ROOT = Path(__file__).resolve().parent.parent
F5_SRC = ROOT / "f5tts_src"
MODEL_DIR = ROOT / "ckpts"          # 官方约定：模型放 ckpts/F5TTS_Base/
if str(F5_SRC) not in sys.path:
    sys.path.insert(0, str(F5_SRC))


def _patch_audioop():
    """Python 3.13 移除了标准库 audioop。

    pydub 的写法是 `try: import audioop / except ImportError: import pyaudioop`，
    而 `pyaudioop` 是 pydub 包内的模块，用裸 import 时依赖 sys.path 里有 pydub 目录，
    在包外调用会失败。这里直接把 audioop 注册成 pyaudioop，两种写法都能用。
    """
    try:
        import audioop as _audioop
    except ImportError:
        try:
            from pydub import pyaudioop as _audioop
        except Exception:
            return
    sys.modules.setdefault("pyaudioop", _audioop)


def _patch_torchaudio_load():
    """绕开 torchaudio 2.9 的破坏性变更。

    torchaudio 2.9 起，`torchaudio.load()` 内部改为调用 TorchCodec，
    官方文档明确写着 backend 参数「被忽略，仅为向后兼容」保留。
    而 TorchCodec 需要 FFmpeg 的动态库（libavcodec 等），
    本工具包自带的是静态编译的单文件 ffmpeg.exe，不含这些 DLL，
    因此 TorchCodec 在本机永远加载不了 —— 与 torch 版本无关。

    F5-TTS 内部用 torchaudio.load 读参考音频，所以我们在这里把它换成
    soundfile（走 libsndfile，零外部依赖）。签名保持一致，避免调用方出错。
    """
    import torch as _torch
    import torchaudio as _torchaudio

    try:
        import soundfile as _sf
    except ImportError:
        return

    def _load(uri, frame_offset=0, num_frames=-1, normalize=True,
              channels_first=True, format=None, buffer_size=4096, backend=None):
        data, sr = _sf.read(str(uri), dtype="float32", always_2d=True)
        wav = _torch.from_numpy(data).t().contiguous()   # [channel, time]
        if frame_offset:
            wav = wav[..., frame_offset:]
        if num_frames is not None and num_frames > 0:
            wav = wav[..., :num_frames]
        if not channels_first:
            wav = wav.t()
        return wav, sr

    _torchaudio.load = _load


_patch_torchaudio_load()


_patch_audioop()

sys.path.insert(0, str(Path(__file__).parent))
from math_speech import convert_math  # noqa: E402


def _cuda_ok():
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


def _ensure_ffmpeg_on_path():
    """transformers / pydub 都要求能找到名为 ffmpeg 的可执行文件。

    .venv-tts 里没装 imageio-ffmpeg（那是主环境 .venv 的依赖），且 imageio 自带的
    文件名叫 ffmpeg-win-x86_64-v7.1.exe，Windows 的 subprocess 只认 ffmpeg.exe。
    这里在临时目录里建一个 ffmpeg.exe 的软链接/副本并加进 PATH，
    不用在系统里装 ffmpeg，也不污染全局环境。
    """
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if shutil.which(exe_name):
        return

    src = None
    bindir = ROOT / ".venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    if bindir.exists():
        hits = [h for h in bindir.glob("ffmpeg*") if h.suffix.lower() in (".exe", "")]
        if hits:
            src = hits[0]
    if src is None:
        return

    link_dir = Path(tempfile.gettempdir()) / "wb_ffmpeg_bin"
    link_dir.mkdir(parents=True, exist_ok=True)
    dst = link_dir / exe_name

    # 用复制而不是软链：Windows 未开开发者模式时 symlink 直接失败，
    # 而某些环境下 os.symlink 会"成功"却生成 0 字节坏链（后续报 WinError 193）。
    real = src.resolve()
    need_copy = True
    if dst.exists() and not dst.is_symlink():
        try:
            need_copy = dst.stat().st_size != real.stat().st_size
        except OSError:
            need_copy = True
    if need_copy:
        if dst.is_symlink() or dst.exists():
            try:
                dst.unlink()
            except OSError:
                pass
        shutil.copy2(real, dst)

    os.environ["PATH"] = str(link_dir) + os.pathsep + os.environ.get("PATH", "")
    os.environ["IMAGEIO_FFMPEG_EXE"] = str(dst)
    os.environ["FFMPEG_BINARY"] = str(dst)


_ensure_ffmpeg_on_path()


def find_model_dir():
    """定位 F5TTS_Base 模型目录（含 model_*.safetensors 与 vocab.txt）。"""
    cands = [
        MODEL_DIR / "F5TTS_Base",
        ROOT / "ckpts" / "F5TTS_Base",
        ROOT / "模型" / "F5TTS_Base",
        ROOT / "f5tts_src" / "ckpts" / "F5TTS_Base",
    ]
    for c in cands:
        if list(c.glob("model_*.safetensors")) and (c / "vocab.txt").exists():
            return c
    return None


# ASR 模型：F5-TTS 官方默认 whisper-large-v3-turbo（1.6GB），
# 但本机 HuggingFace 直连不通，改用已缓存到本地的 whisper-small（约 500MB）。
# 两者对「中文口播稿」的转写精度差异很小，但快 3 倍。
ASR_MODEL = "openai/whisper-small"


def get_ref_text(ref_audio: Path, cache_dir: Path, device="cuda"):
    """转写参考音频里的内容。

    F5-TTS 需要「参考音频 + 该音频对应的文本」才能克隆音色。
    不想每次都转写，就用 --ref-text 手动指定；这里的转写结果会缓存到
    ref_audio.txt，改了录音只需删缓存。
    """
    cache = cache_dir / (ref_audio.stem + ".txt")
    if cache.exists():
        txt = cache.read_text(encoding="utf-8").strip()
        if txt:
            return txt

    print("[ASR] 正在转写参考音频（首次约 20 秒，结果会缓存）...")
    import torch
    from transformers import pipeline

    dtype = torch.float16 if "cuda" in str(device) else torch.float32
    pipe = pipeline("automatic-speech-recognition", model=ASR_MODEL,
                    torch_dtype=dtype,
                    device=0 if "cuda" in str(device) else -1)
    r = pipe(str(ref_audio), language="zh", return_timestamps=False)
    txt = (r.get("text") or "").strip()

    try:
        import torch as _t

        if _t.cuda.is_available():
            _t.cuda.empty_cache()
    except Exception:
        pass

    if txt:
        cache.write_text(txt, encoding="utf-8")
        print(f"[ASR] 转写结果已缓存 → {cache}")
    return txt


def parse_csv(path: Path):
    import csv

    entries = []
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                sample = f.read(2048)
                f.seek(0)
                delim = ";" if sample.count(";") > sample.count(",") else ","
                for row in csv.DictReader(f, delimiter=delim):
                    fn = row.get("filename") or row.get("文件名") or row.get("file")
                    tx = (row.get("text") or row.get("对白") or row.get("content")
                          or row.get("读白") or row.get("文本"))
                    if fn and tx:
                        entries.append((fn.strip(), tx.strip()))
            return entries
        except UnicodeDecodeError:
            continue
    return entries


def parse_md_table(path: Path):
    """与 generate_tts.py 同构：从分镜 md 的音频清单表提取 (文件名, 读白)。"""
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


def read_duration(path: Path) -> float:
    try:
        from mutagen import File as MFile

        m = MFile(str(path))
        if m is not None and getattr(m, "info", None) and m.info.length:
            return float(m.info.length)
    except Exception:
        pass
    try:
        import soundfile as sf

        d = sf.read(str(path))
        return len(d[0]) / float(sf.info(str(path)).samplerate)
    except Exception:
        pass
    return 0.0


def get_ffmpeg():
    """定位 ffmpeg 可执行文件（优先系统，其次工具包自带的）。"""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    p = shutil.which(exe)
    if p:
        return p
    link = Path(tempfile.gettempdir()) / "wb_ffmpeg_bin" / exe
    if link.exists():
        return str(link)
    bindir = ROOT / ".venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    if bindir.exists():
        hits = [h for h in bindir.glob("ffmpeg*") if h.suffix.lower() == ".exe"]
        if hits:
            return str(hits[0])
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def transcode(src: Path, dst: Path, fmt: str) -> bool:
    """把 F5-TTS 产出的 wav 转成目标格式。

    F5-TTS 只会写 wav，但分镜表里的文件名通常写成 .mp3（沿用 edge-tts 的习惯）。
    如果直接把 wav 数据写进 .mp3 文件名，虽然多数播放器能靠内容嗅探打开，
    但属于名实不符，而且 manim 侧读时长可能出错。这里做一次真转码。
    """
    if src.suffix.lower() == dst.suffix.lower():
        return True
    ff = get_ffmpeg()
    if not ff:
        return False
    if dst.suffix.lower() == ".mp3":
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(src), "-codec:a", "libmp3lame", "-b:a", "192k", str(dst)]
    else:
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 512


class Cloner:
    """封装 F5-TTS 模型（官方 f5_tts.api.F5TTS），延迟加载（首次约 20-30 秒）。"""

    _instance = None

    @classmethod
    def get(cls, model_name="F5TTS_Base", device="cuda"):
        if cls._instance is None:
            cls._instance = cls(model_name, device)
        return cls._instance

    def __init__(self, model_name, device):
        import torch
        from f5_tts.api import F5TTS

        md = find_model_dir()
        if md is None:
            raise FileNotFoundError(
                "找不到 F5-TTS 模型。请确认 ckpts/F5TTS_Base/model_1200000.safetensors 存在")

        vocos_dir = ROOT / "ckpts" / "vocos"
        if not (vocos_dir / "pytorch_model.bin").exists():
            raise FileNotFoundError(
                f"找不到 vocos 声码器：{vocos_dir}\n"
                "       下载：https://hf-mirror.com/charactr/vocos-mel-24khz 下的 "
                "config.yaml 与 pytorch_model.bin")

        if device == "cuda" and not torch.cuda.is_available():
            print("[警告] CUDA 不可用，退回 CPU（会慢 10 倍以上）")
            device = "cpu"

        self.device = device
        print(f"[加载] 模型 {model_name} → {device}")
        t0 = time.time()

        # 关键：把 ckpt / vocab / vocos 全部指向本地路径，
        # 否则 API 会去 HuggingFace 下载（本机 HF 直连不通）
        self.f5 = F5TTS(
            model=model_name,
            ckpt_file=str(md / "model_1200000.safetensors"),
            vocab_file=str(md / "vocab.txt"),
            vocoder_local_path=str(vocos_dir),
            device=device,
        )
        print(f"[加载] 完成，耗时 {time.time()-t0:.1f}s")

    def synth(self, ref_audio: str, ref_text: str, gen_text: str, out: str,
               speed=1.0, seed=None, steps=32):
        """把 gen_text 用 ref_audio 的音色念出来，写到 out。"""
        self.f5.infer(
            ref_file=ref_audio,
            ref_text=ref_text,
            gen_text=gen_text,
            file_wave=out,
            speed=speed,
            nfe_step=steps,
            seed=seed,
            remove_silence=False,
            # F5-TTS 内部用 `progress.tqdm(...)`，所以 progress 必须是 tqdm 模块本身；
            # 传 None 表示不显示进度条（这里由我们自己的日志代替）
            progress=None,
            show_info=lambda *a, **k: None,
        )


def main():
    ap = argparse.ArgumentParser(description="声线克隆配音（F5-TTS / GPU）")
    ap.add_argument("input", nargs="?", help="分镜.md 或 CSV（不给则配合 --text 试听）")
    ap.add_argument("outdir", nargs="?", default="./audio")
    ap.add_argument("--text", help="单句试听模式：要合成的文本")
    ap.add_argument("--ref", required=True, help="参考音频（用 prep_voice.py 处理过的）")
    ap.add_argument("--ref-text", default="", help="参考音频里念的内容（留空则自动跳过，会略降相似度）")
    ap.add_argument("--speed", type=float, default=1.0, help="语速，1.0 为原速")
    ap.add_argument("--seed", type=int, default=0, help="随机种子，固定值可复现")
    ap.add_argument("--steps", type=int, default=32, help="推理步数，越大越稳越慢（32 足够）")
    ap.add_argument("--raw", action="store_true", help="不做数学式转读白")
    ap.add_argument("--format", choices=["mp3", "wav"], default="mp3",
                    help="输出格式，默认 mp3（与 generate_tts.py 一致）")
    ap.add_argument("-o", "--output", help="单句模式的输出文件名")
    args = ap.parse_args()

    ref = Path(args.ref)
    if not ref.exists():
        print(f"[错误] 找不到参考音频：{ref}")
        print("       先跑 prep_voice.py 预处理：python 工具脚本/prep_voice.py 录音.m4a -o 声线参考")
        return 1

    # 参考文本：手动指定 > ASR 转写（带缓存）
    ref_text = args.ref_text
    if not ref_text:
        try:
            ref_text = get_ref_text(ref, ref.parent, "cuda" if _cuda_ok() else "cpu")
        except Exception as e:
            print(f"[错误] 无法转写参考音频：{e}")
            print("       可以手动指定：--ref-text \"你录音里念的内容\"")
            return 1
        if not ref_text:
            print("[错误] 转写结果为空。请用 --ref-text 手动指定参考文本。")
            return 1

    try:
        cloner = Cloner.get()
    except Exception as e:
        print(f"[错误] 模型加载失败：{e}")
        return 1

    # ---- 单句试听 ----
    if args.text:
        out = Path(args.output or "试听.wav")
        out.parent.mkdir(parents=True, exist_ok=True)
        text = args.text if args.raw else convert_math(args.text)
        print(f"\n试听合成")
        print(f"  参考音色：{ref.name}")
        print(f"  文本：{text}")
        t0 = time.time()
        try:
            cloner.synth(str(ref), ref_text, text, str(out),
                         speed=args.speed, seed=args.seed, steps=args.steps)
        except Exception as e:
            print(f"[失败] {e}")
            return 1
        dur = read_duration(out)
        print(f"[完成] {out}  {dur:.2f}s  耗时 {time.time()-t0:.1f}s")
        print("\n请用播放器试听，判断音色是否像本人。")
        return 0

    # ---- 批量：从 md / csv 读 ----
    if not args.input:
        print("[错误] 需要 分镜.md / CSV 参数，或用 --text 试听")
        return 1

    src = Path(args.input)
    if not src.exists():
        print(f"[错误] 找不到输入文件：{src}")
        return 1

    entries = parse_md_table(src) if src.suffix.lower() == ".md" else parse_csv(src)
    if not entries:
        print("[错误] 未解析到任何 (文件名, 文本) 对")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"声线克隆配音  设备={cloner.device}  参考={ref.name}  条目={len(entries)}")
    print("=" * 60)

    results = []
    t_start = time.time()
    for i, (raw_name, text) in enumerate(entries, 1):
        name = Path(raw_name).name
        if not name.lower().endswith((".mp3", ".wav")):
            name += "." + args.format
        final_path = outdir / name
        # F5-TTS 只能写 wav：先合成到临时 wav（放系统临时目录：
        # 兼容各类安全删除/回收站策略，且需要时再转码成目标格式）
        import tempfile as _tf

        tmp_wav = Path(_tf.gettempdir()) / ("__tmp_clone_" + Path(name).stem
                                            + f"_{os.getpid()}.wav")

        speech = text if args.raw else convert_math(text)
        print(f"\n[{i}/{len(entries)}] {name}")
        print(f"  原文: {text[:58]}{'...' if len(text) > 58 else ''}")
        if speech != text:
            print(f"  读白: {speech[:58]}{'...' if len(speech) > 58 else ''}")

        t0 = time.time()
        try:
            cloner.synth(str(ref), ref_text, speech, str(tmp_wav),
                         speed=args.speed, seed=args.seed, steps=args.steps)
        except Exception as e:
            print(f"  [失败] {e}")
            continue

        if not tmp_wav.exists():
            print("  [失败] 未生成文件")
            continue

        if final_path.suffix.lower() == ".wav":
            tmp_wav.replace(final_path)
        elif transcode(tmp_wav, final_path, args.format):
            tmp_wav.unlink(missing_ok=True)
        else:
            print("  [警告] 转码失败，保留 wav")
            final_path = tmp_wav

        if not final_path.exists():
            print("  [失败] 目标文件缺失")
            continue

        dur = read_duration(final_path)
        m = re.search(r"(\d+)", Path(name).stem)
        results.append({"scene": int(m.group()) if m else i,
                        "file": final_path.name, "text": text,
                        "duration": round(dur, 3)})
        print(f"  [OK] {dur:.2f}s  ({time.time()-t0:.1f}s)")

    if not results:
        print("\n[失败] 没有成功生成任何音频")
        return 1

    total = sum(r["duration"] for r in results)
    elapsed = time.time() - t_start
    (outdir / "audio_info.json").write_text(
        json.dumps({"files": results, "total_duration": round(total, 3),
                    "count": len(results), "engine": "F5-TTS",
                    "ref_audio": ref.name, "speed": args.speed},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"成功 {len(results)}/{len(entries)}，总时长 {total:.2f}s ({total/60:.2f} 分钟)")
    print(f"生成耗时 {elapsed:.1f}s  （实时率 RTF={elapsed/max(total,0.01):.2f}，<1 表示比播放快）")
    print(f"已写出 {outdir / 'audio_info.json'}")
    print("=" * 60)
    return 0 if len(results) == len(entries) else 1


if __name__ == "__main__":
    sys.exit(main())

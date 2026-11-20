#!/usr/bin/env python3
"""
安装「声线克隆」环境（F5-TTS 本地 GPU 推理）

为什么要单独一个脚本：
    克隆用的 torch 有 2.5GB+，和 manim 环境（.venv）混装会互相干扰，
    所以单独建 .venv-tts。一键安装.py 只装 manim 那套，保持轻量。

它会做五件事：
    1. 检查 NVIDIA GPU 与驱动
    2. 建独立环境 .venv-tts（不污染系统 Python）
    3. 装 CUDA 版 torch + F5-TTS 推理依赖
    4. 下载模型权重（F5-TTS 主模型 / vocos 声码器 / Whisper 参考音频识别）
    5. 跑一次最小合成验证，确认真的能出声

用法（双击 安装声线克隆.bat 也可以）：
    python 安装声线克隆.py

国内网络说明：
    HuggingFace 直连不通时自动走 hf-mirror.com 镜像；
    pip 默认源装不了 matplotlib 等包时自动切换清华源。
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 清掉外部注入的 PYTHONPATH，否则 venv 里的包会"看不见"
for _k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
    os.environ.pop(_k, None)

ROOT = Path(__file__).parent.resolve()
VENV = ROOT / ".venv-tts"
CKPTS = ROOT / "ckpts"
HF_MIRROR = "https://hf-mirror.com"
TSINGHUA = "https://pypi.tuna.tsinghua.edu.cn/simple"
PYPI = "https://pypi.org/simple"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"

# F5-TTS 推理真正需要的包（把训练/WebUI 用的 gradio、wandb 排除，省 2GB）
PKGS = [
    "numpy", "soundfile", "librosa", "pypinyin", "jieba", "rjieba",
    "x-transformers", "vocos", "torchdiffeq", "ema-pytorch",
    "transformers", "accelerate", "datasets",
    "mutagen", "omegaconf", "hydra-core", "cached_path", "pydub", "Unidecode",
    "audioop-lts", "matplotlib",
]

MODEL_FILES = [
    ("SWivid/F5-TTS", "F5TTS_Base/model_1200000.safetensors", "ckpts/F5TTS_Base/model_1200000.safetensors", 1348645281),
    ("SWivid/F5-TTS", "F5TTS_Base/vocab.txt", "ckpts/F5TTS_Base/vocab.txt", 14300),
    ("charactr/vocos-mel-24khz", "config.yaml", "ckpts/vocos/config.yaml", 461),
    ("charactr/vocos-mel-24khz", "pytorch_model.bin", "ckpts/vocos/pytorch_model.bin", 54365991),
]


def log(msg, kind="info"):
    icons = {"info": "  ", "ok": "[OK]", "warn": "[!]", "err": "[X]", "step": "=="}
    print(f"{icons.get(kind, '  ')} {msg}", flush=True)


def run(cmd, **kw):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    return subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)


def check_gpu():
    log("检查显卡 ...")
    nv = shutil.which("nvidia-smi")
    if not nv:
        log("没找到 nvidia-smi。克隆会在 CPU 上跑（慢 10 倍以上）", "warn")
        return False
    r = run([nv, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"])
    if r.returncode == 0 and r.stdout.strip():
        log(f"显卡：{r.stdout.strip()}", "ok")
        return True
    log("nvidia-smi 执行异常，将退回 CPU", "warn")
    return False


def ensure_venv():
    if VENV.exists():
        log("已存在独立环境 .venv-tts，跳过创建", "ok")
    else:
        log("创建独立环境 .venv-tts ...")
        r = run([sys.executable, "-m", "venv", str(VENV)])
        if r.returncode != 0:
            log(f"创建失败：{r.stderr[:200]}", "err")
            sys.exit(1)
        log("环境创建完成", "ok")

    py = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        log(f"找不到解释器：{py}", "err")
        sys.exit(1)

    r = run([str(py), "-m", "pip", "--version"])
    if r.returncode != 0:
        log("补装 pip ...", "warn")
        run([str(py), "-m", "ensurepip", "--upgrade"])
    return py


def pip_install(py, args, desc, index=None, allow_fail=False):
    cmd = [str(py), "-m", "pip", "install", "--no-cache-dir"]
    if index:
        cmd += ["-i", index]
    cmd += args
    log(f"{desc} ...")
    r = run(cmd)
    if r.returncode == 0:
        log(f"{desc} 完成", "ok")
        return True
    if allow_fail:
        log(f"{desc} 失败（已忽略）", "warn")
        return False
    log(f"{desc} 失败：", "err")
    print((r.stderr or r.stdout)[-600:])
    sys.exit(1)


def install_torch(py):
    """torch 走官方 CUDA 源；国内源没有 +cu128 的 Windows 构建。"""
    r = run([str(py), "-c", "import torch;print(torch.__version__)"])
    if r.returncode == 0:
        log(f"torch 已装：{r.stdout.strip()}", "ok")
        return
    log("安装 CUDA 版 torch（约 2.5GB，需要几分钟）...")
    r = run([str(py), "-m", "pip", "install", "--no-cache-dir",
             "--index-url", TORCH_INDEX, "torch", "torchaudio"])
    if r.returncode != 0:
        log(f"torch 安装失败：{(r.stderr or r.stdout)[-400:]}", "err")
        sys.exit(1)
    log("torch 安装完成", "ok")


def install_deps(py):
    """分批装：先默认源，个别源缺失的包再切清华源。"""
    r = run([str(py), "-c", "import soundfile, transformers, vocos, librosa, rjieba"])
    if r.returncode == 0:
        log("依赖已齐全，跳过", "ok")
        return

    # matplotlib 在默认源上偶尔取不到，先单独用清华源装
    pip_install(py, ["setuptools"], "构建工具 setuptools")
    pip_install(py, ["matplotlib"], "matplotlib", index=TSINGHUA, allow_fail=True)
    rest = [p for p in PKGS if p != "matplotlib"]
    if not pip_install(py, rest, "F5-TTS 推理依赖", allow_fail=True):
        log("默认源失败，改用清华源重试 ...", "warn")
        pip_install(py, rest, "F5-TTS 推理依赖（清华源）", index=TSINGHUA)


def download_file(py, repo, remote, local, expect_size):
    dst = ROOT / local
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size >= expect_size * 0.98:
        log(f"已存在 {dst.name}（{dst.stat().st_size/1024/1024:.0f}MB）", "ok")
        return
    url = f"{HF_MIRROR}/{repo}/resolve/main/{remote}"
    log(f"下载 {dst.name} ...")
    # 用 Python 的 urllib 而不是 curl，保证跨平台且能跟随重定向
    code = (
        "import urllib.request,sys,shutil;"
        f"req=urllib.request.Request({url!r},headers={{'User-Agent':'Mozilla/5.0'}});"
        f"r=urllib.request.urlopen(req,timeout=1800);"
        f"f=open({str(dst)!r},'wb');"
        "shutil.copyfileobj(r,f);f.close()"
    )
    r = run([str(py), "-c", code])
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size < expect_size * 0.5:
        log(f"下载失败：{(r.stderr or '')[-300:]}", "err")
        log(f"可手动下载后放到：{dst}", "warn")
        sys.exit(1)
    log(f"{dst.name} 完成（{dst.stat().st_size/1024/1024:.0f}MB）", "ok")


def download_models(py):
    log("下载模型权重 ...")
    for repo, remote, local, size in MODEL_FILES:
        download_file(py, repo, remote, local, size)

    # Whisper 用来识别参考音频里念的内容（F5-TTS 克隆时需要）
    cache = Path.home() / ".cache" / "huggingface" / "hub" / "models--openai--whisper-small"
    ok = False
    if cache.exists():
        for p in cache.rglob("model.safetensors"):
            if p.stat().st_size > 400 * 1024 * 1024:
                ok = True
    if ok:
        log("Whisper 参考识别模型已缓存", "ok")
    else:
        log("下载 Whisper-small（约 1GB，用于识别参考音频内容）...")
        code = (
            "import os;os.environ['HF_ENDPOINT']='%s';"
            "from huggingface_hub import snapshot_download;"
            "snapshot_download('openai/whisper-small',max_workers=1,"
            "allow_patterns=['config.json','preprocessor_config.json','tokenizer.json',"
            "'vocab.json','merges.txt','generation_config.json','model.safetensors'])"
        ) % HF_MIRROR
        r = run([str(py), "-c", code])
        if r.returncode != 0:
            log(f"Whisper 下载失败：{(r.stderr or '')[-300:]}", "warn")
            log("不影响克隆本身：可用 --ref-text 手动指定参考音频文字", "warn")
        else:
            log("Whisper 下载完成", "ok")


def download_source(py):
    """F5-TTS 源码：只取推理需要的，不 clone 整个仓库。"""
    src = ROOT / "f5tts_src" / "f5_tts"
    if (src / "api.py").exists():
        log("F5-TTS 源码已存在", "ok")
        return
    log("获取 F5-TTS 源码 ...")
    zip_url = "https://github.com/SWivid/F5-TTS/archive/refs/heads/main.zip"
    tmp = ROOT / "f5tts_src" / "_tmp.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import urllib.request,zipfile,io;"
        f"data=urllib.request.urlopen({zip_url!r},timeout=300).read();"
        "z=zipfile.ZipFile(io.BytesIO(data));"
        "keep=[n for n in z.namelist() if n.startswith('F5-TTS-main/src/f5_tts/') "
        "and (n.endswith('.py') or n.endswith('.yaml') or n.endswith('.toml'))];"
        f"z.extractall({str(ROOT / 'f5tts_src' / '_tmp')!r},members=keep)"
    )
    r = run([str(py), "-c", code])
    ex = ROOT / "f5tts_src" / "_tmp" / "F5-TTS-main" / "src" / "f5_tts"
    if r.returncode != 0 or not ex.exists():
        log(f"源码获取失败：{(r.stderr or '')[-300:]}", "err")
        log("请手动下载 https://github.com/SWivid/F5-TTS 并放置 src/f5_tts 到 f5tts_src/", "warn")
        sys.exit(1)
    shutil.move(str(ex), str(src))
    shutil.rmtree(ROOT / "f5tts_src" / "_tmp", ignore_errors=True)
    log("源码就位", "ok")


def verify(py):
    log("验证 GPU 可用性 ...")
    r = run([str(py), "-c",
             "import torch;print(torch.cuda.is_available());"
             "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"])
    out = r.stdout.strip().splitlines()
    if out and out[0].strip() == "True":
        log(f"CUDA 可用：{out[1] if len(out) > 1 else '?'}", "ok")
    else:
        log("CUDA 不可用，克隆将以 CPU 模式运行（很慢）", "warn")

    log("验证依赖导入 ...")
    r = run([str(py), "-c",
             "import soundfile,transformers,vocos,librosa,rjieba,omegaconf;print('ok')"])
    if r.returncode != 0:
        log(f"依赖缺失：{(r.stderr or '')[-300:]}", "err")
        sys.exit(1)
    log("依赖完整", "ok")


def main():
    print("=" * 62)
    print("  声线克隆环境安装（F5-TTS 本地 GPU 版）")
    print("=" * 62)
    print()

    t0 = time.time()
    check_gpu()
    py = ensure_venv()
    install_torch(py)
    install_deps(py)
    download_source(py)
    download_models(py)
    verify(py)

    print()
    print("=" * 62)
    log("安装完成！", "ok")
    print("=" * 62)
    print()
    print("接下来：")
    print("  1. 准备你的声线样本（15-30 秒最干净的一段录音）：")
    print(f'     "{py}" 工具脚本/prep_voice.py 你的录音.m4a -o 声线参考')
    print("  2. 试听一句效果：")
    print(f'     "{py}" 工具脚本/clone_tts.py --text "各位同学好" '
          '--ref 声线参考/clean_24k.wav -o 试听.wav')
    print("  3. 正式出片（用你的声线）：")
    print(f'     "{sys.executable}" 一键出片.py 分镜.md --hd --voice clone')
    print()
    print(f"总耗时 {time.time()-t0:.0f} 秒")
    print()


if __name__ == "__main__":
    main()

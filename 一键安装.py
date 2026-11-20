"""
一键安装 —— 在任意 Windows 电脑上搭建教学视频生成环境。

用法（双击 一键安装.bat 即可，或命令行）：
    python 一键安装.py

它会做四件事：
  1. 检查 Python 版本（需要 3.11 ~ 3.13）
  2. 创建独立虚拟环境 .venv（不污染系统），安装 manim 渲染管线依赖
  3. 组装课程工厂需要的目录结构（工具脚本/、声线参考/）
  4. 自检 ffmpeg

装完后：
  - 双击 课程工厂.exe（GUI 一步到位），「设置」里把「教学视频工具包路径」指向本目录
  - 或双击 安装声线克隆.bat 追加 F5-TTS 声线克隆环境（约 4GB 下载）
"""

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
VENV = ROOT / ".venv"
WHEELS = ROOT / "wheels"

# 支持的版本范围（manim 0.21 在 3.13 上实测可用）
MIN_PY, MAX_PY = (3, 11), (3, 13)

# 渲染管线 + 课程工厂源码运行所需的全部包
PKGS = ["manim==0.21.0", "edge-tts", "mutagen", "imageio-ffmpeg", "pillow",
        "numpy", "pypdf", "pypdfium2", "python-docx"]

VOICE_README = """\
这是「声线参考」目录 —— 声线克隆的样本存放处。

用法：
  1. 准备一段 15~30 秒、环境安静、只有你一个人说话的录音（wav/mp3/m4a 均可）
  2. 先跑「安装声线克隆.bat」装好 F5-TTS 环境
  3. 用它自带的 prep_voice 处理成 24kHz 干净样本，命名为 clean_24k.wav 放到本目录
  4. 课程工厂「设置」→「声线参考音频」指向这个文件

没有录音？先用 edge-tts 电子音也能出片（无需本目录）。
"""


def log(msg, kind="info"):
    icons = {"info": "  ", "ok": "[OK]", "warn": "[!]", "err": "[X]"}
    print(f"{icons.get(kind,'  ')} {msg}", flush=True)


def check_python():
    v = sys.version_info
    log(f"检测到 Python {v.major}.{v.minor}.{v.micro}")
    if (v.major, v.minor) < MIN_PY or (v.major, v.minor) > MAX_PY:
        log(f"版本不在支持范围（需要 {MIN_PY[0]}.{MIN_PY[1]} ~ {MAX_PY[0]}.{MAX_PY[1]}）", "err")
        log("请到 https://www.python.org/downloads/ 安装 Python 3.12 后重试", "err")
        sys.exit(1)
    if platform.system() != "Windows":
        log("当前脚本为 Windows 编写，其他系统请自行适配", "warn")
    return True


def find_ffmpeg():
    """manim 渲染必须有 ffmpeg。找不到时用 imageio-ffmpeg 自带的。"""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for p in [r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]:
        if Path(p).exists():
            log(f"找到本机 ffmpeg: {p}", "ok")
            return p
    try:
        import imageio_ffmpeg
        b = imageio_ffmpeg.get_ffmpeg_exe()
        if b and Path(b).exists():
            log(f"将使用 imageio-ffmpeg 自带 ffmpeg: {b}", "ok")
            return b
    except Exception:
        pass
    log("未找到 ffmpeg，安装 imageio-ffmpeg 后可自动使用其内置版本", "warn")
    return None


def run(cmd):
    # 关键：清掉 PYTHONPATH 污染，否则 venv 里的包会"看不见"，甚至 pip 装坏
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def ensure_pip(py):
    """venv 里没有 pip 就补一个。"""
    r = run([str(py), "-m", "pip", "--version"])
    if r.returncode == 0:
        return True
    log("虚拟环境缺少 pip，正在补装 ...", "warn")
    run([str(py), "-m", "ensurepip", "--upgrade"])
    return run([str(py), "-m", "pip", "--version"]).returncode == 0


def assemble_layout():
    """组装课程工厂期望的目录：工具脚本/、声线参考/。"""
    # scripts/*.py → 工具脚本/（课程工厂按 tool_root/工具脚本 调用）
    src = ROOT / "scripts"
    dst = ROOT / "工具脚本"
    if src.exists():
        dst.mkdir(exist_ok=True)
        n = 0
        for f in src.glob("*.py"):
            shutil.copy2(f, dst / f.name)
            n += 1
        log(f"工具脚本/ 已就位（{n} 个脚本）", "ok")
    # 声线参考/ 占位说明（声线样本是私人的，仓库不含）
    vr = ROOT / "声线参考"
    vr.mkdir(exist_ok=True)
    (vr / "README.txt").write_text(VOICE_README, encoding="utf-8")
    log("声线参考/ 已就位（放你自己的录音样本）", "ok")


def main():
    print("=" * 60)
    print("  教学视频生成环境 —— 一键安装")
    print("=" * 60)
    print()

    check_python()

    # 1. 虚拟环境
    if VENV.exists():
        log("已存在虚拟环境 .venv，跳过创建", "ok")
    else:
        log("创建虚拟环境 .venv ...")
        r = run([sys.executable, "-m", "venv", str(VENV)])
        if r.returncode != 0:
            log(f"创建失败：{r.stderr[:200]}", "err")
            sys.exit(1)
        log("虚拟环境创建完成", "ok")

    py = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        log(f"找不到虚拟环境解释器：{py}", "err")
        sys.exit(1)
    log(f"虚拟环境解释器：{py}", "ok")

    if not ensure_pip(py):
        log("虚拟环境里没有可用的 pip，无法继续", "err")
        sys.exit(1)

    # 2. 依赖（联网；清华镜像兜底）
    log("检查依赖 ...")
    r = run([str(py), "-c",
             "import manim, edge_tts, mutagen, imageio_ffmpeg, pypdf, pypdfium2, docx"])
    if r.returncode == 0:
        log("依赖已齐全，跳过安装", "ok")
    else:
        run([str(py), "-m", "pip", "install", "-i",
             "https://pypi.tuna.tsinghua.edu.cn/simple", "setuptools"])
        log("联网安装依赖（清华镜像）...")
        r = run([str(py), "-m", "pip", "install", "-i",
                 "https://pypi.tuna.tsinghua.edu.cn/simple", *PKGS])
        if r.returncode != 0:
            log("清华镜像失败，改用官方源重试 ...", "warn")
            r = run([str(py), "-m", "pip", "install", *PKGS])
        if r.returncode == 0:
            log("依赖安装完成", "ok")
        else:
            log("依赖安装失败：", "err")
            print((r.stdout or "")[-800:])
            print((r.stderr or "")[-800:])
            sys.exit(1)

    # 3. 验证
    log("验证安装 ...")
    r = run([str(py), "-c", "import manim; print(manim.__version__)"])
    if r.returncode == 0:
        log(f"manim 版本 {r.stdout.strip()}", "ok")
    else:
        log("manim 导入失败", "err")
        sys.exit(1)

    # 4. 组装目录结构 + 自检 ffmpeg
    assemble_layout()
    find_ffmpeg()

    print()
    print("=" * 60)
    log("安装完成！", "ok")
    print("=" * 60)
    print()
    print("接下来两种用法：")
    print("  A. 图形界面（推荐）：双击 课程工厂.exe")
    print('     「设置」→「教学视频工具包路径」指向本目录即可')
    print("  B. 命令行：把题目内容写进 分镜.md，参考 docs/pipeline.md")
    print()
    print("想要「自己的声线」配音？再双击 安装声线克隆.bat（约 4GB 下载）")
    print()


if __name__ == "__main__":
    main()

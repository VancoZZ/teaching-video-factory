@echo off
chcp 65001 >nul
title 数学教学视频工具 - 安装声线克隆环境
cd /d "%~dp0"

REM 清掉外部注入的 PYTHONPATH，否则 venv 里的包会"看不见"
set PYTHONPATH=
set PYTHONHOME=

echo.
echo ============================================================
echo   声线克隆环境安装（F5-TTS 本地 GPU 版）
echo ============================================================
echo.
echo   这会下载约 4GB 内容（torch + 模型权重），需要一定时间。
echo   装好后可以用你自己的声线给教学视频配音。
echo.
echo ============================================================
echo.
pause

if exist ".venv-tts\Scripts\python.exe" (
    echo [!] 检测到已存在 .venv-tts，将复用现有环境
    echo.
)

REM 依次尝试：WorkBuddy 自带 3.13 → PATH 里的 python
set "PYEXE="
if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
    set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe"
)
if not defined PYEXE (
    for %%p in (python.exe) do set "PYEXE=%%~$PATH:p"
)
if not defined PYEXE (
    echo [X] 没有检测到 Python
    echo.
    echo 请先安装 Python 3.11 ~ 3.13：
    echo     https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo 使用解释器：%PYEXE%
echo.

"%PYEXE%" 安装声线克隆.py
if errorlevel 1 (
    echo.
    echo [X] 安装失败，请看上面的提示
    pause
    exit /b 1
)

pause

@echo off
chcp 65001 >nul
title 数学教学视频工具 - 一键安装
cd /d "%~dp0"

REM 清掉外部注入的 PYTHONPATH，否则可能指向别的 Python，导致本工具包的依赖"看不见"
set PYTHONPATH=
set PYTHONHOME=

echo.
echo ============================================================
echo   数学教学视频生成工具 —— 一键安装
echo ============================================================
echo.

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
    echo 安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo 使用解释器：%PYEXE%
echo.

"%PYEXE%" 一键安装.py
if errorlevel 1 (
    echo.
    echo [X] 安装失败，请看上面的提示
    pause
    exit /b 1
)

echo.
echo 安装完成。接下来：
echo   1. 双击「复制示例.bat」
echo   2. 用记事本打开 分镜.md 改成你的题目
echo   3. 双击「出片.bat」
echo.
pause

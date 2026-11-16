@echo off
setlocal
cd /d "%~dp0"
title FlowLens
chcp 936 >nul 2>&1
if not exist "logs" md "logs" >nul 2>&1

rem ============================================================
rem  若自动检测不到 Python，请去掉下一行的 rem 并改成你的完整路径：
rem set "PY=C:\Python313\python.exe"
rem ============================================================

rem --- 0. 若已存在打包好的 exe，直接用它（无需 Python） ---
if defined NUM_FORCE_CONSOLE goto :no_exe
if not "%~1"=="" goto :no_exe
set "EXE=%~dp0..\FlowLens.exe"
if not exist "%EXE%" set "EXE=%~dp0FlowLens.exe"
if not exist "%EXE%" goto :no_exe
start "" "%EXE%"
exit /b 0
:no_exe

rem --- 1. py 启动器 ---
if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%i"
    )
)

rem --- 2. PATH 里的 python（跳过微软商店占位程序） ---
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul
        if errorlevel 1 call :take "%%i"
    )
)

rem --- 3. 常见安装位置 ---
if not defined PY call :scan "%LOCALAPPDATA%\Programs\Python" "Python3*"
if not defined PY call :scan "C:" "Python3*"
if not defined PY call :scan "%ProgramFiles%" "Python3*"
if not defined PY call :scan "%ProgramFiles(x86)%" "Python3*"
if not defined PY call :scan "D:\WorkBuddyData\binaries\python\versions" "*"

if not defined PY goto :nopython
echo 解释器: %PY%

rem --- 4. 依赖检查 ---
"%PY%" -c "import PySide6, psutil" >nul 2>&1
if errorlevel 1 (
    echo.
    echo 首次运行需要安装依赖 PySide6 / psutil / openpyxl
    echo 通常需要几分钟，请保持网络畅通...
    "%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo 镜像源未成功，改用官方源重试...
        "%PY%" -m pip install -r requirements.txt
    )
    "%PY%" -c "import PySide6, psutil" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [失败] 依赖安装未完成，请手动执行：
        echo    "%PY%" -m pip install PySide6 psutil openpyxl -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
)

rem --- 5. 启动主程序 ---
if defined NUM_FORCE_CONSOLE set "PYW="
if defined PYW (
    start "" "%PYW%" run.py %*
    exit /b 0
)
"%PY%" run.py %*
set "RC=%errorlevel%"
if defined NUM_SHOW_LOG call :showlog
if not "%RC%"=="0" (
    echo.
    echo 程序异常退出（exit %RC%），详细信息见 logs\app.log
    pause
)
exit /b %RC%

:scan
if defined PY goto :eof
for /f "delims=" %%N in ('dir /b /ad "%~1\%~2" 2^>nul') do (
    if not defined PY call :take "%~1\%%N\python.exe"
)
goto :eof

:take
if defined PY goto :eof
if not exist "%~1" goto :eof
"%~1" -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
for %%I in ("%~1") do set "PYDIR=%%~dpI"
set "PY=%~1"
if exist "%PYDIR%pythonw.exe" set "PYW=%PYDIR%pythonw.exe"
goto :eof

:showlog
echo.
echo ---- 最近日志 logs\app.log ----
"%PY%" -c "import pathlib,sys; p=pathlib.Path('logs/app.log'); d=p.read_bytes().decode('utf-8','replace') if p.exists() else 'no log recorded yet'; sys.stdout.buffer.write(d[-1500:].encode('gbk','replace'))" 2>nul
echo.
goto :eof

:nopython
echo.
echo ============================================================
echo   未找到可用的 Python
echo ============================================================
echo 本程序需要 64 位 Python 3.9 或更高版本。
echo 系统里的 "python" 命令可能指向微软商店的占位程序，无法执行脚本。
echo.
echo 解决办法（任选其一）：
echo   1^) 安装 Python：https://www.python.org/downloads/windows/
echo      安装时务必勾选 "Add python.exe to PATH"，然后重新运行本文件。
echo   2^) 右键本文件 - 编辑，把 set "PY=..." 那行的 rem 去掉并填上
echo      你机器上 python.exe 的完整路径，例如：
echo         set "PY=C:\Python313\python.exe"
echo.
pause
exit /b 1

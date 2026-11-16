@echo off
setlocal
cd /d "%~dp0"
set "NUM_FORCE_CONSOLE=1"
set "NUM_SHOW_LOG=1"
call "%~dp0run.bat" %*
echo.
pause

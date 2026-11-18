@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "C:\ProgramData\Anaconda3\Library\bin" (
    set "PATH=C:\ProgramData\Anaconda3\Library\bin;C:\ProgramData\Anaconda3;%PATH%"
)

if exist "C:\ProgramData\Anaconda3\python.exe" (
    "C:\ProgramData\Anaconda3\python.exe" "%~dp0app.py"
) else (
    python "%~dp0app.py"
)

if errorlevel 1 (
    echo.
    echo [提示] 程序异常退出，请查看上方错误信息。
    pause
)

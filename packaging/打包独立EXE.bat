@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo ========================================================
echo   AI BOARD 独立桌面客户端打包工具 (供分发上线他人使用)
echo ========================================================
echo.

if exist "C:\ProgramData\Anaconda3\Library\bin" (
    set "PATH=C:\ProgramData\Anaconda3\Library\bin;C:\ProgramData\Anaconda3;C:\ProgramData\Anaconda3\Scripts;%PATH%"
)

:: 1. 检查 PyInstaller 是否已安装
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [1/3] 正在安装打包工具 PyInstaller...
    python -m pip install "pyinstaller<5.0"
)

:: 2. 生成 512px 超采样多尺寸高清图标 assets\ai_board.ico
echo [2/3] 正在生成高清应用图标 assets\ai_board.ico ...
python -c "import os, sys; sys.path.insert(0, os.getcwd()); import app; from PyQt5 import QtWidgets; q=QtWidgets.QApplication([]); from ui.theme import ensure_app_ico_file; ensure_app_ico_file(os.path.join(os.getcwd(), 'assets', 'ai_board.ico'))"

:: 3. 执行无黑框独立目录打包 (启动速度最快、体积紧凑、无需目标机器装 Python)
echo [3/3] 正在构建独立可执行程序 dist\AIBoard\AIBoard.exe ...
python -m PyInstaller --noconfirm --clean --windowed ^
    --name "AIBoard" ^
    --icon "assets\ai_board.ico" ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module scipy ^
    --exclude-module notebook ^
    --exclude-module IPython ^
    --exclude-module tkinter ^
    app.py

echo.
if exist "dist\AIBoard\AIBoard.exe" (
    echo [完成] 打包成功！可将 dist\AIBoard 整个文件夹压缩分发给任何 Windows 用户直接使用！
) else (
    echo [提示] 打包未生成目标文件，请检查上方日志。
)
pause

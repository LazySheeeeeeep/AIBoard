@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "C:\ProgramData\Anaconda3\Library\bin" (
    set "PATH=C:\ProgramData\Anaconda3\Library\bin;C:\ProgramData\Anaconda3;%PATH%"
)

:: 先确保生成高清多尺寸专属图标 assets\ai_board.ico
if not exist "%~dp0assets\ai_board.ico" (
    if exist "C:\ProgramData\Anaconda3\python.exe" (
        "C:\ProgramData\Anaconda3\python.exe" -c "import os, sys; sys.path.insert(0, r'%~dp0'); import app; from PyQt5 import QtWidgets; q=QtWidgets.QApplication([]); from ui.theme import ensure_app_ico_file; ensure_app_ico_file(os.path.join(r'%~dp0', 'assets', 'ai_board.ico'))"
    ) else (
        python -c "import os, sys; sys.path.insert(0, r'%~dp0'); import app; from PyQt5 import QtWidgets; q=QtWidgets.QApplication([]); from ui.theme import ensure_app_ico_file; ensure_app_ico_file(os.path.join(r'%~dp0', 'assets', 'ai_board.ico'))"
    )
)

set "TARGET_VBS=%~dp0launch_silent.vbs"
set "WORK_DIR=%~dp0"
set "ICO_FILE=%~dp0assets\ai_board.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desk = [Environment]::GetFolderPath('Desktop'); $lnk = $ws.CreateShortcut((Join-Path $desk 'AI BOARD.lnk')); $lnk.TargetPath = 'wscript.exe'; $lnk.Arguments = '\"' + '%TARGET_VBS%' + '\"'; $lnk.WorkingDirectory = '%WORK_DIR%'; if (Test-Path '%ICO_FILE%') { $lnk.IconLocation = '%ICO_FILE%,0' }; $lnk.Description = 'AI BOARD 常驻桌面看板'; $lnk.Save(); Write-Host '已在桌面成功创建带高清专属图标的【AI BOARD】快捷方式！' -ForegroundColor Green"
pause

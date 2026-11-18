# AI BOARD uninstaller
#   aiboard uninstall            remove program, shortcuts, autostart (keeps your todos)
#   aiboard uninstall -Purge     also delete saved data (%APPDATA%\AIBoard)
param([switch]$Purge)

$InstallDir = Join-Path $env:LOCALAPPDATA "AIBoard"
$DataDir    = Join-Path $env:APPDATA "AIBoard"

Write-Host "==> Removing autostart entry ..." -ForegroundColor Cyan
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "AIBoard" -ErrorAction SilentlyContinue

Write-Host "==> Stopping running instance ..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*AIBoard*app.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "==> Removing shortcuts ..." -ForegroundColor Cyan
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "AI BOARD.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Programs")) "AI BOARD.lnk") -ErrorAction SilentlyContinue

Write-Host "==> Cleaning PATH ..." -ForegroundColor Cyan
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $newPath = ($userPath -split ";" | Where-Object { $_ -and ($_ -ne $InstallDir) }) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
}

if ($Purge -and (Test-Path $DataDir)) {
    Write-Host "==> Deleting saved data $DataDir ..." -ForegroundColor Yellow
    Remove-Item $DataDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "==> Removing program files ..." -ForegroundColor Cyan
Set-Location $env:TEMP
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "AI BOARD has been uninstalled." -ForegroundColor Green
if (-not $Purge) { Write-Host "Your todos are kept in $DataDir (use -Purge to delete)." -ForegroundColor DarkGray }

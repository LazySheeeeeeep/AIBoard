# AI BOARD one-line installer for Windows
#   irm https://raw.githubusercontent.com/LazySheeeeeeep/AIBoard/main/install.ps1 | iex
#
# Env options:
#   $env:AIBOARD_YES = "1"         -> non-interactive setup with recommended defaults
#   $env:AIBOARD_SKIP_SETUP = "1"  -> skip the setup wizard (used by `aiboard update`)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo       = "LazySheeeeeeep/AIBoard"
$Branch     = "main"
$InstallDir = Join-Path $env:LOCALAPPDATA "AIBoard"
$StateFile  = Join-Path $env:APPDATA "AIBoard\dashboard_state.json"

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  AI BOARD  -  Desktop dashboard for AI quota, sessions & todos" -ForegroundColor White
Write-Host "  https://github.com/$Repo" -ForegroundColor DarkGray
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Locate a usable Python (>= 3.7), install one via winget if missing
# ---------------------------------------------------------------------------
function Test-Python($exe, $extraArgs) {
    try {
        $out = & $exe @extraArgs -c "import sys; print(sys.executable if sys.version_info >= (3, 7) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $path = ($out | Select-Object -Last 1).Trim()
            if ($path -and (Test-Path $path) -and ($path -notmatch "WindowsApps")) { return $path }
        }
    } catch { }
    return $null
}

function Find-Python {
    $cands = @(
        @("py", @("-3")),
        @("python", @()),
        @("python3", @())
    )
    foreach ($c in $cands) {
        if (Get-Command $c[0] -ErrorAction SilentlyContinue) {
            $p = Test-Python $c[0] $c[1]
            if ($p) { return $p }
        }
    }
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:ProgramData\Anaconda3\python.exe",
        "$env:ProgramData\Miniconda3\python.exe"
    )
    foreach ($g in $globs) {
        foreach ($f in (Get-ChildItem $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
            $p = Test-Python $f.FullName @()
            if ($p) { return $p }
        }
    }
    return $null
}

Step "Checking Python ..."
$Python = Find-Python
if (-not $Python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Warn "Python not found, installing Python 3.12 via winget (user scope) ..."
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $Python = Find-Python
    }
    if (-not $Python) {
        throw "Python 3.7+ not found. Please install it from https://www.python.org/downloads/ and re-run this command."
    }
}
$PythonW = Join-Path (Split-Path $Python -Parent) "pythonw.exe"
if (-not (Test-Path $PythonW)) { $PythonW = $Python }
Ok "Using $Python"

# ---------------------------------------------------------------------------
# 2. Download latest source
# ---------------------------------------------------------------------------
Step "Downloading AI BOARD ($Branch) ..."
$tmp = Join-Path $env:TEMP ("aiboard_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp "src.zip"
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$srcRoot = Get-ChildItem $tmp -Directory | Select-Object -First 1

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item -Path (Join-Path $srcRoot.FullName "*") -Destination $InstallDir -Recurse -Force
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Ok "Installed to $InstallDir"

# ---------------------------------------------------------------------------
# 3. Dependencies
# ---------------------------------------------------------------------------
Step "Installing dependencies (PyQt5) ..."
& $Python -c "import PyQt5.QtWidgets" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install --user --disable-pip-version-check -q -r (Join-Path $InstallDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed." }
    Ok "PyQt5 installed"
} else {
    Ok "PyQt5 already available"
}

# ---------------------------------------------------------------------------
# 4. `aiboard` command + shortcuts
# ---------------------------------------------------------------------------
Step "Registering 'aiboard' command and shortcuts ..."
$cmd = @"
@echo off
setlocal
set "AIB_PY=$Python"
set "AIB_PYW=$PythonW"
set "AIB_HOME=%~dp0"
if /i "%~1"=="setup"     ( "%AIB_PY%" "%AIB_HOME%app.py" --setup %2 %3 & exit /b )
if /i "%~1"=="status"    ( "%AIB_PY%" "%AIB_HOME%app.py" --status & exit /b )
if /i "%~1"=="update"    ( powershell -NoProfile -ExecutionPolicy Bypass -Command "`$env:AIBOARD_SKIP_SETUP='1'; irm https://raw.githubusercontent.com/$Repo/$Branch/install.ps1 | iex" & exit /b )
if /i "%~1"=="uninstall" ( powershell -NoProfile -ExecutionPolicy Bypass -File "%AIB_HOME%uninstall.ps1" & exit /b )
start "" "%AIB_PYW%" "%AIB_HOME%app.py" %*
"@
[IO.File]::WriteAllText((Join-Path $InstallDir "aiboard.cmd"), $cmd, [Text.Encoding]::Default)

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if (($userPath -split ";") -notcontains $InstallDir) {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $InstallDir).TrimStart(";"), "User")
}
$env:Path = $env:Path + ";" + $InstallDir

$ws = New-Object -ComObject WScript.Shell
$ico = Join-Path $InstallDir "assets\ai_board.ico"
$lnkTargets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "AI BOARD.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "AI BOARD.lnk")
)
foreach ($lnkPath in $lnkTargets) {
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = $PythonW
    $lnk.Arguments = '"' + (Join-Path $InstallDir "app.py") + '"'
    $lnk.WorkingDirectory = $InstallDir
    if (Test-Path $ico) { $lnk.IconLocation = "$ico,0" }
    $lnk.Description = "AI BOARD"
    $lnk.Save()
}
Ok "Desktop & Start Menu shortcuts created"

# ---------------------------------------------------------------------------
# 5. One-click setup wizard (first install only) + launch
# ---------------------------------------------------------------------------
$firstInstall = -not (Test-Path $StateFile)
if ($env:AIBOARD_SKIP_SETUP -ne "1" -and $firstInstall) {
    Step "Running setup wizard ..."
    if ($env:AIBOARD_YES -eq "1") {
        & $Python (Join-Path $InstallDir "app.py") --setup --yes
    } else {
        & $Python (Join-Path $InstallDir "app.py") --setup
    }
}

Step "Launching AI BOARD ..."
Start-Process -FilePath $PythonW -ArgumentList ('"' + (Join-Path $InstallDir "app.py") + '"') -WorkingDirectory $InstallDir

Write-Host ""
Write-Host "  Done! Commands (open a NEW terminal):" -ForegroundColor Green
Write-Host "    aiboard            start the dashboard"
Write-Host "    aiboard setup      re-run the setup wizard"
Write-Host "    aiboard update     update to the latest version"
Write-Host "    aiboard uninstall  remove AI BOARD"
Write-Host ""

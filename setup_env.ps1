# setup_env.ps1
#
# One-click environment setup for the Thermal Monitoring System v2.
#
# On a fresh PC this script will:
#   1. Locate a Python 3.10 interpreter (requires Python 3.10.x 64-bit).
#   2. Install the global packages taken from requirements-global.txt
#      (HALCON interface, NumPy, OpenCV, PyQt5, harvesters, genicam).
#   3. Create the project virtual environment (.venv) with
#      --system-site-packages if it does not exist yet.
#   4. Install the development packages from requirements-dev.txt
#      inside the venv (PyQt6, pytest, ruff, debugpy, psutil).
#   5. Verify everything with tools/check_environment.py.
#   6. Activate the venv so the project can be started immediately.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup_env.ps1
#
# Optional parameters:
#   -BasePython <path>   Use a specific Python 3.10 executable.
#   -RecreateVenv        Delete and recreate the venv from scratch.
#   -SkipGlobal          Do not touch the global Python installation.
#
# Windows PowerShell 5.1 compatible.

param(
    [string]$BasePython = "",
    [switch]$RecreateVenv,
    [switch]$SkipGlobal
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir     = Join-Path $ProjectRoot ".venv"
$VenvPython  = Join-Path $VenvDir "Scripts\python.exe"
$GlobalReqs  = Join-Path $ProjectRoot "requirements-global.txt"
$DevReqs     = Join-Path $ProjectRoot "requirements-dev.txt"
$CheckScript = Join-Path $ProjectRoot "tools\check_environment.py"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==== $Message ====" -ForegroundColor Cyan
}

function Find-DefaultPython310 {
    # 1) Explicit -BasePython parameter.
    if ($BasePython -and (Test-Path -LiteralPath $BasePython)) {
        return (Resolve-Path -LiteralPath $BasePython).Path
    }

    # 2) py launcher for 3.10.
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $exe = (& $py.Source "-3.10" "-c" "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
            if ($exe -and (Test-Path -LiteralPath $exe)) {
                return $exe
            }
        } catch {
            # fall through
        }
    }

    # 3) Common installation paths (64-bit Python 3.10).
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python310\python.exe",
        "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python310\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) {
            return $c
        }
    }

    # 4) python.exe from PATH if it is 3.10.
    $pythonCmd = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        try {
            $ver = (& $pythonCmd.Source "-c" "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null | Select-Object -First 1)
            if ($ver -eq "3.10") {
                return $pythonCmd.Source
            }
        } catch {
            # fall through
        }
    }

    return ""
}

function Confirm-Python310([string]$Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) {
        return $false
    }
    try {
        $majorMinor = (& $Exe "-c" "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null | Select-Object -First 1)
        return $majorMinor -eq "3.10"
    } catch {
        return $false
    }
}

# ---------------------------------------------------------------------------
# 1. Python 3.10
# ---------------------------------------------------------------------------
Write-Step "Locating Python 3.10"
$Python310 = Find-DefaultPython310
if (-not (Confirm-Python310 $Python310)) {
    Write-Host "ERROR: Python 3.10 (64-bit) was not found." -ForegroundColor Red
    Write-Host "Install Python 3.10.7 64-bit, then run this script again."
    Write-Host "Download: https://www.python.org/downloads/release/python-3107/"
    exit 1
}
Write-Host "Using Python: $Python310"

# ---------------------------------------------------------------------------
# 2. Global packages (only when requested / first setup)
# ---------------------------------------------------------------------------
if (-not $SkipGlobal) {
    Write-Step "Installing global packages (requirements-global.txt)"
    Write-Host "HALCON runtime (24.11) must already be installed on this machine."
    Write-Host "If mvtec-halcon fails, install and re-run. Installing..." -ForegroundColor Yellow
    & $Python310 "-m" "pip" "install" "--upgrade" "pip"
    if ($LASTEXITCODE -ne 0) { Write-Host "WARNING: pip upgrade failed, continuing." -ForegroundColor Yellow }
    & $Python310 "-m" "pip" "install" "-r" $GlobalReqs
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "ERROR: global package installation failed." -ForegroundColor Red
        Write-Host "Verify the HALCON runtime is installed (C:\Program Files\MVTec\HALCON-*) and re-run."
        Write-Host "Tip: install requirements-global.txt manually:"
        Write-Host "  $Python310 -m pip install -r $GlobalReqs"
        exit 1
    }
} else {
    Write-Step "Skipping global package installation (-SkipGlobal)"
}

# ---------------------------------------------------------------------------
# 3. Virtual environment
# ---------------------------------------------------------------------------
Write-Step "Preparing virtual environment"
if (Test-Path -LiteralPath $VenvDir) {
    if ($RecreateVenv) {
        Write-Host "Removing existing .venv (RecreateVenv)" -ForegroundColor Yellow
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    } else {
        Write-Host ".venv already exists - reusing it."
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Creating virtual environment with --system-site-packages ..."
    & $Python310 "-m" "venv" "--system-site-packages" $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: failed to create the virtual environment." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "venv interpreter already present: $VenvPython"
}

# ---------------------------------------------------------------------------
# 4. Development packages inside the venv
# ---------------------------------------------------------------------------
Write-Step "Installing development packages (requirements-dev.txt)"
& $VenvPython "-m" "pip" "install" "--upgrade" "pip"
& $VenvPython "-m" "pip" "install" "-r" $DevReqs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: dev package installation failed." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 5. Verification
# ---------------------------------------------------------------------------
Write-Step "Verifying environment"
if (Test-Path -LiteralPath $CheckScript) {
    & $VenvPython $CheckScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Environment check reported failures." -ForegroundColor Red
        Write-Host "See docs/Development_Setup.md for repair steps."
        exit 1
    }
} else {
    Write-Host "check_environment.py not found - skipping verification." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 6. Activate the venv for this session
# ---------------------------------------------------------------------------
Write-Step "Done"
Write-Host "Virtual environment ready: $VenvDir" -ForegroundColor Green
Write-Host ""
Write-Host "Activating venv for this session ..." -ForegroundColor Cyan
& (Join-Path $VenvDir "Scripts\Activate.ps1")

Write-Host ""
Write-Host "Environment ready. Start the application with:" -ForegroundColor Green
Write-Host '    python main.py'
Write-Host "or run Windows batch launcher:" -ForegroundColor Green
Write-Host '    start_app.bat'
# setup_env.ps1
#
# Convenience wrapper around setup_environment.py.
#
# The actual setup logic (Python 3.10 detection, .venv creation, pip
# installs, HALCON runtime detection, verification) lives in
# setup_environment.py so that the same one-command setup works from both
# PowerShell and CMD.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File setup_env.ps1
#
# Optional parameters:
#   -BasePython <path>   Use a specific Python 3.10 executable.
#   -RecreateVenv        Delete and recreate the venv from scratch.
#
# Windows PowerShell 5.1 compatible.

param(
    [string]$BasePython = "",
    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupScript = Join-Path $ProjectRoot "setup_environment.py"

if (-not (Test-Path -LiteralPath $SetupScript)) {
    Write-Host "ERROR: setup_environment.py not found next to setup_env.ps1." -ForegroundColor Red
    exit 1
}

if ($BasePython) {
    & $BasePython $SetupScript $(if ($RecreateVenv) { "--recreate" })
} else {
    python $SetupScript $(if ($RecreateVenv) { "--recreate" })
}

exit $LASTEXITCODE

param(
    [string]$PackPath = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\app\main.py")) {
    throw "Run this from D:\Alexa_lite\Alexa_lite (the Sara project root)."
}

$installer = Join-Path $PackPath "install_sara_startup_experience.py"

if (-not (Test-Path $installer)) {
    throw "Cannot find install_sara_startup_experience.py in $PackPath"
}

python $installer

python -m py_compile .\app\main.py
python -m py_compile .\app\audio\startup_experience.py

Write-Host ""
Write-Host "Sara startup pack installed and compiled successfully."
Write-Host "Run: python -m app.main"

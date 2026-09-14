$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SIA MULTILINGUAL STT SETUP - FIXED" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

Set-Location "D:\Alexa_lite\Alexa_lite"

$python = (Get-Command python).Source
Write-Host "Python: $python"
Write-Host ""

# ============================================================
# 1. PACKAGE
# ============================================================

Write-Host "[1/4] Checking faster-whisper..." -ForegroundColor Yellow

& $python -c "import faster_whisper; print('faster-whisper already available')" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing faster-whisper..."
    & $python -m pip install faster-whisper

    if ($LASTEXITCODE -ne 0) {
        throw "faster-whisper installation failed."
    }
}

Write-Host ""

# ============================================================
# 2. MODEL DIRECTORY
# ============================================================

Write-Host "[2/4] Creating model directory..." -ForegroundColor Yellow

$modelDir = Join-Path (Get-Location) "models\faster_whisper\small"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

Write-Host "Model directory: $modelDir"
Write-Host ""

# ============================================================
# 3. DOWNLOAD
# ============================================================

Write-Host "[3/4] Downloading multilingual Whisper small model..." -ForegroundColor Yellow

$env:SIA_FW_MODEL_DIR = $modelDir

@'
import os
from huggingface_hub import snapshot_download

model_dir = os.environ["SIA_FW_MODEL_DIR"]

path = snapshot_download(
    repo_id="Systran/faster-whisper-small",
    local_dir=model_dir,
)

print("Downloaded model to:", path)
'@ | & $python -

if ($LASTEXITCODE -ne 0) {
    throw "Model download failed."
}

Write-Host ""

# ============================================================
# 4. VERIFY
# ============================================================

Write-Host "[4/4] Verifying Faster-Whisper model load..." -ForegroundColor Yellow

@'
import os
from faster_whisper import WhisperModel

model_dir = os.environ["SIA_FW_MODEL_DIR"]

model = WhisperModel(
    model_dir,
    device="cpu",
    compute_type="int8",
)

print("Multilingual STT OK")
print("Model:", model_dir)
print("Device: CPU")
print("Compute: int8")
'@ | & $python -

if ($LASTEXITCODE -ne 0) {
    throw "Faster-Whisper verification failed."
}

Write-Host ""
Write-Host "Checking Python dependency consistency..." -ForegroundColor Yellow

& $python -m pip check

if ($LASTEXITCODE -ne 0) {
    throw "Python dependency consistency check failed."
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "SIA MULTILINGUAL STT SETUP COMPLETE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green

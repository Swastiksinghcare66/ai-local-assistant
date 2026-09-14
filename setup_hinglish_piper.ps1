$ErrorActionPreference = "Stop"

Set-Location "D:\Alexa_lite\Alexa_lite"

Write-Host "============================================================"
Write-Host "SIA HINGLISH / HINDI PIPER SETUP"
Write-Host "============================================================"

$python = (Get-Command python).Source
Write-Host "Python:" $python

Write-Host "`n[1/4] Checking Piper package..."
& python -c "import piper; print('Piper package already available')" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Piper is not installed. Installing piper-tts..."
    & python -m pip install piper-tts
    if ($LASTEXITCODE -ne 0) {
        throw "piper-tts installation failed."
    }
}

Write-Host "`n[2/4] Preparing voice directory..."
$voiceDir = Join-Path (Get-Location) "models\piper"
New-Item -ItemType Directory -Force -Path $voiceDir | Out-Null

$model = Join-Path $voiceDir "hi_IN-priyamvada-medium.onnx"
$config = Join-Path $voiceDir "hi_IN-priyamvada-medium.onnx.json"

if ((Test-Path $model) -and (Test-Path $config)) {
    Write-Host "Hindi voice already downloaded."
}
else {
    Write-Host "`n[3/4] Downloading hi_IN-priyamvada-medium..."
    & python -m piper.download_voices --data-dir $voiceDir hi_IN-priyamvada-medium
    if ($LASTEXITCODE -ne 0) {
        throw "Hindi Piper voice download failed."
    }
}

Write-Host "`n[4/4] Verifying model load..."
& python -c "from piper import PiperVoice; v=PiperVoice.load(r'$model', config_path=r'$config', use_cuda=False); print('Piper Hindi OK | sample_rate=', v.config.sample_rate)"
if ($LASTEXITCODE -ne 0) {
    throw "Piper Hindi model verification failed."
}

Write-Host "`nChecking Python dependency consistency..."
& python -m pip check

Write-Host "`n============================================================"
Write-Host "SIA HINGLISH PIPER SETUP COMPLETE"
Write-Host "Model:" $model
Write-Host "============================================================"

param(
    [string]$Repo = "D:\Alexa_lite\Alexa_lite"
)

$ErrorActionPreference = "Stop"

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $Repo "firmware\esp32_s3"

if (-not (Test-Path $Repo)) {
    throw "Repo not found: $Repo"
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $Repo "_firmware_backup_$stamp"

Write-Host "Backing up existing firmware..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $backup -Force | Out-Null

if (Test-Path $Target) {
    Copy-Item $Target (Join-Path $backup "esp32_s3") -Recurse -Force
}

Write-Host "Backup: $backup" -ForegroundColor Green

Write-Host "Replacing firmware\esp32_s3 with ESP-IDF production baseline..." -ForegroundColor Cyan

if (Test-Path $Target) {
    Remove-Item $Target -Recurse -Force
}

New-Item -ItemType Directory -Path $Target -Force | Out-Null

Get-ChildItem $Source -Force |
    Where-Object {
        $_.Name -ne "install_into_alexa_lite.ps1"
    } |
    Copy-Item -Destination $Target -Recurse -Force

Copy-Item `
    (Join-Path $Source "install_into_alexa_lite.ps1") `
    (Join-Path $Target "install_into_alexa_lite.ps1") `
    -Force

Write-Host ""
Write-Host "Installed production firmware baseline." -ForegroundColor Green
Write-Host "Target: $Target"
Write-Host ""
Write-Host "Next: open an ESP-IDF terminal and run:" -ForegroundColor Yellow
Write-Host "  cd $Target"
Write-Host "  idf.py set-target esp32s3"
Write-Host "  idf.py fullclean"
Write-Host "  idf.py build"

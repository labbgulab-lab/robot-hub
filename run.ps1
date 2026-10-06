# Robot Hub - one-command start (Windows).
#   .\run.ps1            start the hub
#   .\run.ps1 -Doctor    check the environment instead of starting

param([switch]$Doctor, [switch]$NoBrowser)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venv = Join-Path $PSScriptRoot ".venv"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating .venv ..." -ForegroundColor Cyan
    $launcher = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
    if ($launcher -eq "py") { & py -3 -m venv $venv } else { & python -m venv $venv }
    & $py -m pip install --upgrade pip --quiet
    & $py -m pip install -r requirements.txt
}

if (-not (Test-Path (Join-Path $PSScriptRoot "config.toml"))) {
    Write-Host "No config.toml - using config.example.toml. Copy and edit it to set your paths." -ForegroundColor Yellow
}

if ($Doctor) { & $py -m hub.doctor; exit $LASTEXITCODE }

$port = 8099
$cfg = Join-Path $PSScriptRoot "config.toml"
if (Test-Path $cfg) {
    $m = Select-String -Path $cfg -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
    if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
}

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($u) Start-Sleep -Seconds 2; Start-Process $u
    } -ArgumentList "http://127.0.0.1:$port/" | Out-Null
}

Write-Host "Robot Hub -> http://127.0.0.1:$port/" -ForegroundColor Green
& $py -m hub.main

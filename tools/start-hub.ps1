# Robot Hub - what "Start Robot Hub.cmd" runs on a double-click.
#   1. Hub already running: just open its page.
#   2. First time: put a "Robot Hub" shortcut on the desktop.
#   3. Get the latest code (robot-hub, and reachy_chat / NAO_LLM next to it,
#      as tools/setup-windows.ps1 lays them out). If that fails (no internet,
#      local changes), start the version this laptop has.
#   4. Start the hub (run.ps1), which opens the browser.
# Closing the window stops the hub.

$hub = Split-Path $PSScriptRoot -Parent
Set-Location $hub

$port = 8099
$cfg = Join-Path $hub "config.toml"
if (Test-Path $cfg) {
    $m = Select-String -Path $cfg -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
    if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
}
$url = "http://127.0.0.1:$port/"

try {
    Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null
    Write-Host "The hub is already running - opening it." -ForegroundColor Green
    Start-Process $url
    Start-Sleep -Seconds 2
    exit 0
} catch { }

# A Claude session started in the folder above finds how to open the hub. Only
# in the setup-windows.ps1 layout (robot-lab\ with reachy_chat or NAO_LLM).
$parent = Split-Path $hub -Parent
$pointer = Join-Path $parent "CLAUDE.md"
$labLayout = (Test-Path (Join-Path $parent "reachy_chat")) -or (Test-Path (Join-Path $parent "NAO_LLM"))
$pointerText = ('To open the Robot Hub for someone, follow robot-hub/CLAUDE.md: give them the ' +
    'command "%USERPROFILE%\robot-lab\robot-hub\Start Robot Hub.cmd" to run in their own CMD ' +
    'window (never run the hub inside Claude: closing Claude would stop it), then give them ' +
    'the link http://127.0.0.1:8099/')
# Write it, or replace our own older wording; never touch a CLAUDE.md someone else wrote.
$ours = (-not (Test-Path $pointer)) -or ((Get-Content $pointer -Raw) -like "To open the Robot Hub*")
if ($labLayout -and $ours) {
    Set-Content -Path $pointer -Encoding UTF8 -Value $pointerText
}

$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Robot Hub.lnk"
if (-not (Test-Path $lnk)) {
    try {
        $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
        $s.TargetPath = Join-Path $hub "Start Robot Hub.cmd"
        $s.WorkingDirectory = $hub
        $s.Description = "Start the Robot Hub"
        $s.Save()
        Write-Host "Made a 'Robot Hub' shortcut on the desktop - next time, just double-click it." -ForegroundColor Cyan
    } catch { }
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "Getting the latest version ..." -ForegroundColor Cyan
    $parent = Split-Path $hub -Parent
    foreach ($dir in @($hub, (Join-Path $parent "reachy_chat"), (Join-Path $parent "NAO_LLM"))) {
        if (-not (Test-Path (Join-Path $dir ".git"))) { continue }
        $name = Split-Path $dir -Leaf
        git -C $dir pull --ff-only --quiet 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "   $name : up to date" }
        else { Write-Host "   $name : could not update - using the version on this laptop" -ForegroundColor Yellow }
    }
}

& (Join-Path $hub "run.ps1")

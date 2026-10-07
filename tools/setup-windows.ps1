# Robot Hub - set up a lab member's Windows laptop for all robots.
#
#   powershell -ExecutionPolicy Bypass -File setup-windows.ps1 -Kit D:\robot-lab-kit
#
# -Kit is the folder handed over on a USB stick. It holds what is not on
# GitHub: the pynaoqi SDK zip (NAO + Pepper) and the Python 2.7 installer.
# Pepper's dashboard is in robot-hub\pepper_dashboard since 2026-10-07.
#
# Installs (only what is missing): Git, Python 3.12, Python 2.7.
# Puts everything side by side in $HOME\robot-lab:
#   robot-hub\  reachy_chat\  NAO_LLM\  naoqi-sdk\
# Safe to run again: finished steps are skipped.

param(
    [Parameter(Mandatory = $true)][string]$Kit,
    [string]$Root = (Join-Path $HOME "robot-lab")
)

$ErrorActionPreference = "Stop"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Done($text) { Write-Host "   $text" -ForegroundColor Green }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-Winget($id, $test, $label) {
    if (& $test) { Done "$label already installed"; return }
    Write-Host "   installing $label ..."
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (& $test)) { throw "$label did not install - install it by hand and run this again" }
    Done "$label installed"
}

$Kit = (Resolve-Path $Kit).Path
$sdkZip = Get-ChildItem $Kit -Filter "pynaoqi-python2.7-*win64*.zip" | Select-Object -First 1
if (-not $sdkZip) { throw "No pynaoqi-python2.7-...-win64....zip in $Kit" }

# ---------------------------------------------------------------- programs
Step "Programs"
Ensure-Winget "Git.Git" { [bool](Get-Command git -ErrorAction SilentlyContinue) } "Git"
Ensure-Winget "Python.Python.3.12" { [bool](& py -3.12 -c "print(1)" 2>$null) } "Python 3.12"
$py2 = "C:\Python27\python.exe"
# Python 2.7 from the kit's own installer when it is there (no download, the
# exact version the robots were tested with), else from winget.
$py2Msi = Get-ChildItem $Kit -Filter "python-2.7*.amd64.msi" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not (Test-Path $py2) -and $py2Msi) {
    Write-Host "   installing Python 2.7 from $($py2Msi.Name) (Windows asks for permission) ..."
    $p = Start-Process msiexec.exe -Verb RunAs -Wait -PassThru -ArgumentList `
        "/i `"$($py2Msi.FullName)`" /qn ALLUSERS=1 TARGETDIR=C:\Python27\"
    if ($p.ExitCode -ne 0 -or -not (Test-Path $py2)) {
        throw "Python 2.7 did not install (msiexec exit $($p.ExitCode)) - run $($py2Msi.Name) by hand into C:\Python27"
    }
    Done "Python 2.7 installed from the kit"
} else {
    Ensure-Winget "Python.Python.2" { Test-Path $py2 } "Python 2.7"
}

# ------------------------------------------------------------------ code
Step "Code from GitHub -> $Root"
New-Item -ItemType Directory -Force $Root | Out-Null
$repos = @(
    @{ dir = "robot-hub";   url = "https://github.com/labbgulab-lab/robot-hub.git"; branch = "" },
    @{ dir = "reachy_chat"; url = "https://github.com/Tomer232/reachy-mini-conversation-app-bgu-lab.git"; branch = "multi-provider" },
    @{ dir = "NAO_LLM";     url = "https://github.com/Tomer232/antagonistic-robot.git"; branch = "" }
)
foreach ($r in $repos) {
    $path = Join-Path $Root $r.dir
    if (Test-Path (Join-Path $path ".git")) {
        git -C $path pull --ff-only | Out-Null
        Done "$($r.dir): updated"
    } elseif ($r.branch) {
        git clone -q -b $r.branch $r.url $path; Done "$($r.dir): cloned ($($r.branch))"
    } else {
        git clone -q $r.url $path; Done "$($r.dir): cloned"
    }
}

# ------------------------------------------------------------------- kit
Step "Kit: NAOqi SDK"
$sdkDir = Join-Path $Root "naoqi-sdk"
# The SDK root is the folder whose lib\ holds naoqi.py.
function Find-Sdk {
    Get-ChildItem $sdkDir -Recurse -Filter naoqi.py -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq "lib" } | Select-Object -First 1
}
$naoqiPy = Find-Sdk
if (-not $naoqiPy) {
    Write-Host "   unpacking $($sdkZip.Name) (1 GB unpacked, a few minutes) ..."
    Expand-Archive -Path $sdkZip.FullName -DestinationPath $sdkDir -Force
    $naoqiPy = Find-Sdk
    if (-not $naoqiPy) { throw "naoqi.py not found after unpacking $($sdkZip.Name)" }
}
$sdk = $naoqiPy.Directory.Parent.FullName
Done "SDK at $sdk"

& $py2 -c "import sys; sys.path.insert(0, r'$sdk\lib'); import os; os.environ['PATH'] = r'$sdk\bin;' + os.environ['PATH']; import naoqi; print('naoqi ok')"
if ($LASTEXITCODE -ne 0) { throw "Python 2.7 cannot import naoqi from $sdk" }

# ------------------------------------------------------------ environments
Step "Python environments (NAO_LLM downloads PyTorch: 5-15 minutes)"
$envs = @(
    @{ dir = "reachy_chat"; venv = ".venv" },
    @{ dir = "NAO_LLM";     venv = "venv" }
)
foreach ($e in $envs) {
    $repo = Join-Path $Root $e.dir
    $python = Join-Path $repo "$($e.venv)\Scripts\python.exe"
    if (-not (Test-Path $python)) { & py -3.12 -m venv (Join-Path $repo $e.venv) }
    Write-Host "   $($e.dir): installing requirements ..."
    & $python -m pip install --upgrade pip --quiet
    & $python -m pip install -r (Join-Path $repo "requirements.txt") --quiet
    if ($LASTEXITCODE -ne 0) { throw "pip failed in $($e.dir)" }
    Done "$($e.dir) ready"
}

# NAO_LLM loads its speech model before its page opens; on a new laptop that
# is a 141 MB download, which outlasted the hub's Launch wait (2026-10-06).
Step "NAO_LLM speech model (about 140 MB, once)"
$naoPython = Join-Path $Root "NAO_LLM\venv\Scripts\python.exe"
& $naoPython -c "from faster_whisper import download_model; download_model('base.en', use_auth_token=False); print('speech model ready')"
if ($LASTEXITCODE -ne 0) { throw "could not download NAO_LLM's speech model - check the internet and run this again" }

# ----------------------------------------------------------------- config
Step "Hub configuration"
$hub = Join-Path $Root "robot-hub"
$cfg = Join-Path $hub "config.toml"
if (-not (Test-Path $cfg)) {
    $text = Get-Content (Join-Path $hub "config.example.toml") -Raw
    $text = $text -replace '(?m)^(\s*python2\s*=\s*)".*"', ('$1"' + ($py2 -replace '\\', '/') + '"')
    $text = $text -replace '(?m)^(\s*pynaoqi_sdk\s*=\s*)".*"', ('$1"' + ($sdk -replace '\\', '/') + '"')
    Set-Content -Path $cfg -Value $text -Encoding UTF8
    Done "config.toml written (Python 2.7 + SDK paths set)"
} else { Done "config.toml already there - left as it is" }
foreach ($pair in @(@($hub, ".env.example", ".env"), @((Join-Path $Root "NAO_LLM"), ".env.example", ".env"))) {
    $target = Join-Path $pair[0] $pair[2]
    if (-not (Test-Path $target)) { Copy-Item (Join-Path $pair[0] $pair[1]) $target; Done "created $target" }
}

Step "Finished"
Write-Host @"
   Now put the keys in (see API-KEYS.md in the kit):
     $hub\.env            FURHAT_PASSWORD=...
     $Root\NAO_LLM\.env   GROK_API_KEY=...  OPENAI_API_KEY=...
   Start the hub:
     cd $hub ; .\run.ps1
   Then, on the page: Speaking keys -> add the Gemini / OpenAI / ElevenLabs keys,
   and Network setup -> check the hotspot.
"@ -ForegroundColor Green

# Build the student app bundle: dist\RobotHub-<version>.zip (+ dist\install.ps1).
#
#   powershell -ExecutionPolicy Bypass -File tools\build_release.ps1                  # HEAD of both repos
#   powershell -ExecutionPolicy Bypass -File tools\build_release.ps1 -FromWorkingTree # uncommitted work too
#
# Options: -Ref <git ref of robot-hub> (default HEAD), -ReachyChat <checkout>
# (default ..\reachy_chat or ..\reachy-mini\reachy_chat), -ReachyChatRef
# (default multi-provider), -Version (default: the VERSION file, else 0.0.0),
# -OutDir (default dist), -KeepStaging.
#
# What goes in (docs/BUILD-PLAN.md, "Install layout"; STUDENT-APP-PLAN 2.4):
#   runtime\      python-build-standalone CPython 3.12 (pinned + sha256-checked)
#                 with requirements.txt + tools\release-extra-requirements.txt
#                 pip-installed INTO it (no venv: venvs hard-code their paths),
#                 plus the VC++ runtime DLLs it lacks, copied app-local
#   robot-hub\    git archive of -Ref (or the tracked + untracked-not-ignored
#                 files with -FromWorkingTree), without tests, docs, dev scripts
#   reachy_chat\  the same for reachy_chat (deployed onto the robots by the hub)
#   launch.pyw, VERSION, install.ps1, "Install Robot Hub.cmd"
#
# Never in the zip: git-ignored files, keys.local.json, .env, config.toml,
# group.local.json, logs\, cache\, data\, key files. The build removes any it
# finds and then fails if a file name or a key-shaped string is still there.

param(
    [string]$Ref = "HEAD",
    [switch]$FromWorkingTree,
    [string]$ReachyChat = "",
    [string]$ReachyChatRef = "multi-provider",
    [string]$Version = "",
    [string]$OutDir = "",
    [switch]$KeepStaging
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# CPython 3.12 (3.13 drops audioop, which pepper_app uses). Bump both lines together.
$PythonUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20261021/cpython-3.12.15%2B20261021-x86_64-pc-windows-msvc-install_only.tar.gz"
$PythonSha256 = "be7f14464d1d66f84429ad27e01f6d1482963afff64a2fb5256b2a51c7b5d398"

$VcDlls = @("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
            "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll")

# Files and folders that are never shipped, wherever they are.
$SecretNames = @("keys.local.json", ".env", "config.toml", "group.local.json", "keys.json", "backend.json",
                 "hf_token.txt", "hf_token.txt.bak", ".gemini_key", "openai_key.txt", "elevenlabs_key.txt",
                 "robot_identity.json", "persona.json", "known_addresses.json", "settings.json")
$SecretPatterns = @("*_key.txt", "*.key", "*.gemini_key", ".keys-*", "*.skill", "*.log")
$NeverDirs = @("logs", "cache", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
               "conversations", "system_logs", "archive", "backups")
# Key-shaped strings (OpenAI/OpenRouter, Gemini, ElevenLabs, Hugging Face).
$KeyRegex = 'sk-(or-v1-)?[A-Za-z0-9_\-]{32,}|AIza[0-9A-Za-z_\-]{35}|sk_[0-9a-f]{40,}|hf_[A-Za-z0-9]{30,}'

# Per repo: what a student's laptop does not need.
$HubDrop = @("docs", "tests", "launch", ".github", ".gitignore", ".gitattributes", ".env.example", "CLAUDE.md",
             "NEXT-SESSION.md", "PLAN.md", "run.ps1", "run.sh", "Start Robot Hub.cmd", "pepper_app\data", "data",
             "tools\build_release.ps1", "tools\install.ps1", "tools\make_icon.py",
             "tools\release-extra-requirements.txt", "tools\release-constraints.txt",
             "tools\setup-windows.ps1", "tools\start-hub.ps1",
             "tools\build_release_mac.sh", "tools\install-mac.sh", "tools\release-constraints-mac.txt")
$ChatDrop = @("docs", "tests", ".gitignore", ".gitattributes", "show\audio", "show\backups")

$hubRepo = Split-Path $PSScriptRoot -Parent
if (-not $OutDir) { $OutDir = Join-Path $hubRepo "dist" }
$OutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
$tar = Join-Path $env:SystemRoot "System32\tar.exe"
$t0 = Get-Date

function Get-Sha256([string]$Path) {
    # .NET directly: Get-FileHash is missing when Windows PowerShell inherits PowerShell 7's module path.
    $fs = [IO.File]::OpenRead($Path)
    try { $sha = [Security.Cryptography.SHA256]::Create(); -join ($sha.ComputeHash($fs) | ForEach-Object { $_.ToString("x2") }) }
    finally { $fs.Dispose() }
}

function Step($text) { Write-Host ("[{0,5:n0}s] {1}" -f ((Get-Date) - $t0).TotalSeconds, $text) -ForegroundColor Cyan }

function Invoke-Native([string]$What, [scriptblock]$Cmd) {
    # Windows PowerShell turns a native tool's stderr into errors under Stop.
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $Cmd } finally { $ErrorActionPreference = $old }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function Export-Repo([string]$Repo, [string]$GitRef, [string]$Dest) {
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    if ($FromWorkingTree) {
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $list = & git -C $Repo ls-files -co --exclude-standard -z
        $ErrorActionPreference = $old
        if ($LASTEXITCODE -ne 0) { throw "git ls-files failed in $Repo" }
        $n = 0
        foreach ($rel in ($list -split "`0")) {
            if (-not $rel) { continue }
            $src = Join-Path $Repo $rel
            if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }   # deleted, not yet committed
            $dst = Join-Path $Dest $rel
            $dir = Split-Path $dst -Parent
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            Copy-Item -LiteralPath $src -Destination $dst
            $n++
        }
        Write-Host "    $n files from the working tree of $Repo"
    } else {
        $tmp = Join-Path $staging "export.tar"
        Invoke-Native "git archive ($GitRef)" { git -C $Repo archive --format=tar -o $tmp $GitRef }
        Invoke-Native "unpacking the git archive" { & $tar -x -f $tmp -C $Dest }
        Remove-Item -LiteralPath $tmp -Force
        $sha = (& git -C $Repo rev-parse --short "$GitRef^{commit}")
        Write-Host "    $GitRef ($sha) of $Repo"
    }
}

function Remove-Listed([string]$Base, [string[]]$Rel) {
    foreach ($r in $Rel) {
        $p = Join-Path $Base $r
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
    }
}

function Remove-Secrets([string]$Base) {
    $hits = @()
    Get-ChildItem -LiteralPath $Base -Recurse -Force -Directory |
        Where-Object { $NeverDirs -contains $_.Name } | Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object { if (Test-Path -LiteralPath $_.FullName) { Remove-Item -LiteralPath $_.FullName -Recurse -Force } }
    Get-ChildItem -LiteralPath $Base -Recurse -Force -File | ForEach-Object {
        $f = $_
        $bad = ($SecretNames -contains $f.Name)
        foreach ($pat in $SecretPatterns) { if ($f.Name -like $pat) { $bad = $true } }
        if ($bad) { $hits += $f.FullName; Remove-Item -LiteralPath $f.FullName -Force }
    }
    foreach ($h in $hits) { Write-Warning "left out a private file: $($h.Substring($Base.Length + 1))" }
}

function Assert-Clean([string]$Base) {
    $files = Get-ChildItem -LiteralPath $Base -Recurse -Force -File
    foreach ($f in $files) {
        $bad = ($SecretNames -contains $f.Name)
        foreach ($pat in $SecretPatterns) { if ($f.Name -like $pat) { $bad = $true } }
        if ($bad) { throw "private file in the bundle: $($f.FullName)" }
    }
    $text = $files | Where-Object { $_.Extension -in @(".py", ".json", ".toml", ".txt", ".md", ".js", ".html", ".css", ".yaml", ".yml", ".ps1", ".cmd", ".sh", ".cfg", ".ini", "") -and $_.Length -lt 5MB }
    $found = $text | Select-String -Pattern $KeyRegex -CaseSensitive -List
    if ($found) {
        $found | ForEach-Object { Write-Warning "key-shaped string: $($_.Path):$($_.LineNumber)" }
        throw "the bundle looks like it holds a key; nothing was zipped"
    }
}

# ---------------------------------------------------------------- inputs
if (-not $ReachyChat) {
    foreach ($c in @((Join-Path $hubRepo "..\reachy_chat"), (Join-Path $hubRepo "..\reachy-mini\reachy_chat"))) {
        if (Test-Path (Join-Path $c "conversation.py")) { $ReachyChat = $c; break }
    }
}
if (-not $ReachyChat -or -not (Test-Path $ReachyChat)) { throw "reachy_chat checkout not found; pass -ReachyChat <folder>" }
$ReachyChat = (Resolve-Path $ReachyChat).Path
if ($FromWorkingTree) {
    $branch = (& git -C $ReachyChat rev-parse --abbrev-ref HEAD)
    if ($branch -ne $ReachyChatRef) { Write-Warning "reachy_chat is on '$branch', not '$ReachyChatRef'" }
}

if (-not $Version) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    if ($FromWorkingTree) {
        $vf = Join-Path $hubRepo "VERSION"
        if (Test-Path $vf) { $Version = (Get-Content $vf -Raw).Trim() }
    } else {
        $v = & git -C $hubRepo show "${Ref}:VERSION" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { $Version = ($v | Out-String).Trim() }
    }
    $ErrorActionPreference = $old
    if (-not $Version) { $Version = "0.0.0" }
}
if ($Version -notmatch '^[0-9A-Za-z.+\-]+$') { throw "odd version '$Version'" }

$staging = Join-Path $OutDir "build"
$app = Join-Path $staging "app"
$cache = Join-Path $OutDir "cache"
$zip = Join-Path $OutDir "RobotHub-$Version.zip"
Step "Robot Hub $Version -> $zip"
if (Test-Path $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $app, $cache | Out-Null

# ---------------------------------------------------------------- (a) (b) sources
Step "robot-hub"
Export-Repo $hubRepo $Ref (Join-Path $app "robot-hub")
Remove-Listed (Join-Path $app "robot-hub") $HubDrop
Remove-Secrets (Join-Path $app "robot-hub")

Step "reachy_chat"
Export-Repo $ReachyChat $ReachyChatRef (Join-Path $app "reachy_chat")
Remove-Listed (Join-Path $app "reachy_chat") $ChatDrop
Remove-Secrets (Join-Path $app "reachy_chat")

# ---------------------------------------------------------------- (c) runtime
$pyTgz = Join-Path $cache ([Uri]::UnescapeDataString(($PythonUrl -split "/")[-1]))
if (-not (Test-Path $pyTgz) -or (Get-Sha256 $pyTgz) -ne $PythonSha256) {
    Step "downloading CPython"
    Invoke-WebRequest -Uri $PythonUrl -OutFile $pyTgz -UseBasicParsing
}
$hash = (Get-Sha256 $pyTgz)
if ($hash -ne $PythonSha256) { Remove-Item -LiteralPath $pyTgz -Force; throw "CPython download has the wrong sha256 ($hash)" }
Step "runtime (sha256 ok)"
Invoke-Native "unpacking CPython" { & $tar -x -f $pyTgz -C $app }
Rename-Item -LiteralPath (Join-Path $app "python") -NewName "runtime"
$py = Join-Path $app "runtime\python.exe"

Step "pip install into the runtime"
$env:PYTHONNOUSERSITE = "1"
$env:PIP_USER = "0"
$env:PIP_REQUIRE_VIRTUALENV = "0"
Remove-Item Env:PYTHONPATH, Env:PYTHONHOME, Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
$old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $py -c "import pip" 2>$null
$hasPip = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $old
if (-not $hasPip) { Invoke-Native "ensurepip" { & $py -m ensurepip --default-pip } }
$reqHub = Join-Path $app "robot-hub\requirements.txt"
if (-not (Test-Path $reqHub)) { $reqHub = Join-Path $hubRepo "requirements.txt" }
Invoke-Native "pip install" {
    & $py -m pip install --disable-pip-version-check --no-warn-script-location --prefer-binary `
        -r $reqHub -r (Join-Path $PSScriptRoot "release-extra-requirements.txt") `
        -c (Join-Path $PSScriptRoot "release-constraints.txt")
}

# ---------------------------------------------------------------- (d) VC++ runtime, app-local
$rt = Join-Path $app "runtime"
foreach ($dll in $VcDlls) {
    $dst = Join-Path $rt $dll
    $src = Join-Path $env:SystemRoot "System32\$dll"
    if (-not (Test-Path $dst) -and (Test-Path $src)) { Copy-Item -LiteralPath $src -Destination $dst; Write-Host "    + $dll" }
}

# ---------------------------------------------------------------- (e) prune, compile, smoke test
Step "pruning"
$lib = Join-Path $rt "Lib"
$site = Join-Path $lib "site-packages"
Remove-Listed $rt @("include", "libs", "Scripts", "Lib\test", "Lib\idlelib", "Lib\lib2to3\tests", "Lib\ensurepip\_bundled",
                   "Lib\site-packages\PyWin32.chm")
Get-ChildItem -LiteralPath $site -Recurse -Directory -Filter "tests" | Sort-Object { $_.FullName.Length } -Descending |
    ForEach-Object { if (Test-Path -LiteralPath $_.FullName) { Remove-Item -LiteralPath $_.FullName -Recurse -Force } }
Get-ChildItem -LiteralPath $site -Directory -Filter "*.dist-info" | ForEach-Object {
    Remove-Item -LiteralPath (Join-Path $_.FullName "RECORD") -Force -ErrorAction SilentlyContinue
}
Get-ChildItem -LiteralPath $app -Recurse -Directory -Filter "__pycache__" | ForEach-Object {
    if (Test-Path -LiteralPath $_.FullName) { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}

Step "compileall"
# The runtime never changes after install: unchecked-hash pycs load without a
# look at the source, however the zip was unpacked. The hub's own code is
# checked against its source. reachy_chat is not compiled: it goes to robots.
$old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
& $py -m compileall -q -j 0 --invalidation-mode unchecked-hash $lib | Out-Null
& $py -m compileall -q -j 0 --invalidation-mode checked-hash (Join-Path $app "robot-hub") | Out-Null
$ErrorActionPreference = $old

Step "smoke test"
Invoke-Native "importing the hub's packages" {
    & $py -I -c "import fastapi, uvicorn, pydantic_settings, httpx, websockets, zeroconf, psutil, paramiko, numpy, onnxruntime, soundfile, sounddevice, tomli_w, wmi, win32com.client, pystray, PIL; print('    packages import')"
}
Push-Location (Join-Path $app "robot-hub")
try { Invoke-Native "importing hub.config" { & $py -I -c "import sys; sys.path.insert(0, '.'); import hub.config; print('    hub.config imports')" } }
finally { Pop-Location }

# ---------------------------------------------------------------- (f) launcher, version, installer
Set-Content -LiteralPath (Join-Path $app "VERSION") -Value $Version -Encoding ASCII -NoNewline
Set-Content -LiteralPath (Join-Path $app "robot-hub\VERSION") -Value $Version -Encoding ASCII -NoNewline
Copy-Item -LiteralPath (Join-Path $hubRepo "launch\launch.pyw") -Destination $app
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install.ps1") -Destination $app
Set-Content -LiteralPath (Join-Path $app "Install Robot Hub.cmd") -Encoding ASCII -Value @(
    "@echo off",
    "rem For laptops that block the one-line install: unzip, then double-click this.",
    "powershell -NoProfile -ExecutionPolicy Bypass -File ""%~dp0install.ps1"" -Source ""%~dp0.""",
    "pause")

Assert-Clean (Join-Path $app "robot-hub")
Assert-Clean (Join-Path $app "reachy_chat")
$longest = Get-ChildItem -LiteralPath $app -Recurse -File | ForEach-Object { $_.FullName.Length - $app.Length } | Measure-Object -Maximum
# %LOCALAPPDATA%\LabaLab\RobotHub\app.new\ is about 70 characters on a long user name; MAX_PATH is 260.
if ($longest.Maximum -gt 180) { Write-Warning "longest path inside the bundle: $($longest.Maximum) characters" }

# ---------------------------------------------------------------- (g) zip
Step "zipping"
if (Test-Path $zip) { Remove-Item -LiteralPath $zip -Force }
$entries = Get-ChildItem -LiteralPath $app -Force | ForEach-Object { $_.Name }
Invoke-Native "tar -a" { & $tar -a -c -f $zip -C $app @entries }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install.ps1") -Destination (Join-Path $OutDir "install.ps1") -Force
$zipHash = (Get-Sha256 $zip)
Set-Content -LiteralPath "$zip.sha256" -Value "$zipHash  RobotHub-$Version.zip" -Encoding ASCII

$appMb = [math]::Round(((Get-ChildItem -LiteralPath $app -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
$zipMb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
if (-not $KeepStaging) { Remove-Item -LiteralPath $staging -Recurse -Force }
Step "done"
Write-Host ""
Write-Host "  $zip"
Write-Host "  zip $zipMb MB, installed $appMb MB, sha256 $zipHash"
Write-Host "  $(Join-Path $OutDir 'install.ps1')"
Write-Host "  Release: tag v$Version, assets RobotHub-$Version.zip and install.ps1."

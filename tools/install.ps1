# LabaLab Robot Hub installer. For this Windows user only: no admin, no Python,
# no Git. Running it again updates. Windows PowerShell 5.1 or PowerShell 7.
#
#   irm https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install.ps1 | iex
#
# Or with options (a saved copy of this file):
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Zip RobotHub-x.y.z.zip]
#       [-Root <folder>] [-NoLaunch] [-Uninstall [-RemoveData]]
#
# Layout (docs/BUILD-PLAN.md, "Install layout"):
#   <Root>\app\       replaced on every install; the previous one stays as app.old
#   <Root>\data\      the student's keys, settings, logs: never touched here
#                     (only -Uninstall -RemoveData deletes it)
# Root defaults to %LOCALAPPDATA%\LabaLab\RobotHub.
#
# This file is also the release asset install.ps1, and it sits in the zip
# (with "Install Robot Hub.cmd") for laptops that block the one-line command.

param(
    [string]$Zip = "",            # install from this zip instead of downloading
    [string]$Source = "",         # install from an unpacked bundle folder (the zip fallback)
    [string]$Root = "",
    [string]$Repo = "labbgulab-lab/robot-hub",
    [switch]$Uninstall,
    [switch]$RemoveData,
    [switch]$NoLaunch,
    [switch]$NoShortcuts,
    [string]$DesktopDir = "",     # tests point these at a temp folder
    [string]$StartMenuDir = ""
)

function Install-RobotHub {
    param([string]$Zip, [string]$Source, [string]$Root, [string]$Repo, [switch]$Uninstall,
          [switch]$RemoveData, [switch]$NoLaunch, [switch]$NoShortcuts,
          [string]$DesktopDir, [string]$StartMenuDir)

    # Local to this function, so a pasted `irm | iex` leaves the window as it was.
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"     # the progress bar makes downloads 10x slower
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    $name = "LabaLab Robot Hub"
    if (-not $Root) { $Root = Join-Path $env:LOCALAPPDATA "LabaLab\RobotHub" }
    function Get-FullPath($p) { $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($p) }
    $Root = Get-FullPath $Root
    $app = Join-Path $Root "app"
    $appNew = Join-Path $Root "app.new"
    $appOld = Join-Path $Root "app.old"
    $data = Join-Path $Root "data"
    if (-not $DesktopDir) { $DesktopDir = [Environment]::GetFolderPath("Desktop") }
    if (-not $StartMenuDir) { $StartMenuDir = [Environment]::GetFolderPath("Programs") }
    $links = @((Join-Path $DesktopDir "$name.lnk"), (Join-Path $StartMenuDir "$name.lnk"))
    $tar = Join-Path $env:SystemRoot "System32\tar.exe"

    # The app's Update button starts this installer with the hub's own folder
    # (app\robot-hub) as its current directory, and Windows will not rename a
    # folder a process is in: the swap below then failed every time, in every
    # version up to 1.0.8. Step out of the install first, both PowerShell's
    # location and the process's own directory. Apps of any version fetch the
    # latest release's installer, so this fixes their Update too.
    $rootSlash = $Root.TrimEnd('\') + '\'
    $here = @([IO.Directory]::GetCurrentDirectory())
    try { $here += (Get-Location).ProviderPath } catch { }
    foreach ($p in $here) {
        if ($p -and ($p.TrimEnd('\') + '\').StartsWith($rootSlash, [StringComparison]::OrdinalIgnoreCase)) {
            $away = [Environment]::GetFolderPath("UserProfile")
            Set-Location -LiteralPath $away
            [IO.Directory]::SetCurrentDirectory($away)
            break
        }
    }
    # Started by the app (powershell -Command ...), the window closes the moment
    # this script ends, so a failure would flash by unread: keep it up a while.
    $fromApp = [Environment]::CommandLine -match '-Command'

    function Say($text) { Write-Host "  $text" }
    function Done($text) { Write-Host "  done  " -ForegroundColor Green -NoNewline; Write-Host $text }
    function Fail($text) {
        Write-Host ""; Write-Host "  $text" -ForegroundColor Red; Write-Host ""
        if ($fromApp) { Write-Host "  This window closes in 60 s."; Start-Sleep -Seconds 60 }
    }

    function Get-Sha256([string]$Path) {
        # .NET directly: Get-FileHash is missing when Windows PowerShell inherits PowerShell 7's module path.
        $fs = [IO.File]::OpenRead($Path)
        try { $sha = [Security.Cryptography.SHA256]::Create(); -join ($sha.ComputeHash($fs) | ForEach-Object { $_.ToString("x2") }) }
        finally { $fs.Dispose() }
    }

    function Get-HubPort {
        $port = 8099
        $cfg = Join-Path $data "config.toml"
        if (Test-Path $cfg) {
            $m = Select-String -Path $cfg -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
            if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
        }
        return $port
    }

    function Get-OurProcesses {
        # The launcher, the hub and anything else running from app\ (or the
        # leftovers of a failed swap). Path is readable for our own processes.
        $dirs = @($app, $appNew, $appOld) | ForEach-Object { $_.TrimEnd('\') + '\' }
        Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $p = $null
            try { $p = $_.Path } catch { }
            if (-not $p) { return $false }
            foreach ($d in $dirs) { if ($p.StartsWith($d, [StringComparison]::OrdinalIgnoreCase)) { return $true } }
            return $false
        }
    }

    function Stop-RobotHub {
        # Only a hub started from this install is asked to quit: a lab
        # checkout's hub on the same port is left alone.
        if (@(Get-OurProcesses).Count -eq 0) { return }
        Say "Closing the running Robot Hub ..."
        try {
            $port = Get-HubPort
            Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/app/quit" -Method Post -UseBasicParsing -TimeoutSec 4 | Out-Null
        } catch { }
        for ($i = 0; $i -lt 30; $i++) {
            if (@(Get-OurProcesses).Count -eq 0) { break }
            Start-Sleep -Milliseconds 500
        }
        Get-OurProcesses | ForEach-Object { try { $_.Kill() } catch { } }
        # The app window: Edge with our own profile folder.
        $edgeProfile = Join-Path $data "edge-profile"
        try {
            Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'" -ErrorAction Stop |
                Where-Object { $_.CommandLine -and $_.CommandLine.Contains($edgeProfile) } |
                ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { } }
        } catch { }
        Start-Sleep -Milliseconds 500
    }

    function Remove-Folder($path) {
        # Remove-Item -Recurse in Windows PowerShell 5.1 can leave a big tree
        # behind without an error (seen once in testing): check, then rd /s.
        for ($i = 0; $i -lt 5 -and (Test-Path -LiteralPath $path); $i++) {
            try { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop } catch { }
            if (Test-Path -LiteralPath $path) {
                & cmd.exe /d /c "rd /s /q `"$path`"" 2>$null | Out-Null
                if (Test-Path -LiteralPath $path) { Start-Sleep -Seconds 1 }
            }
        }
        if (Test-Path -LiteralPath $path) { throw "Could not remove $path (is a file in it open?)" }
    }

    function Get-ReleaseZip($dest) {
        $headers = @{ "User-Agent" = "LabaLab-RobotHub-installer"; "Accept" = "application/vnd.github+json" }
        $asset = $null; $digest = $null
        try {
            # Not /releases/latest: the repo's "robot-files" release (the hub's
            # robot files library) can be the latest one. The newest release
            # that carries a RobotHub-*.zip is the app.
            $rels = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases?per_page=30" -Headers $headers -TimeoutSec 30
            foreach ($rel in $rels) {
                if ($rel.draft -or $rel.prerelease) { continue }
                $asset = $rel.assets | Where-Object { $_.name -like "RobotHub-*.zip" } | Select-Object -First 1
                if ($asset) { break }
            }
            if ($asset) { $url = $asset.browser_download_url; $size = $asset.size; $digest = $asset.digest }
        } catch { $asset = $null }
        if (-not $asset) {
            # The API allows 60 calls an hour per address; the release page's
            # redirect names the latest tag (v<version>) without it.
            $req = [Net.HttpWebRequest]::Create("https://github.com/$Repo/releases/latest")
            $req.AllowAutoRedirect = $false
            $req.UserAgent = $headers["User-Agent"]
            $resp = $req.GetResponse()
            $loc = $resp.Headers["Location"]; $resp.Close()
            $tag = if ($loc) { ($loc -split "/tag/")[-1] } else { "" }
            if ($tag -notmatch '^v\d') { throw "No Robot Hub release was found." }
            $url = "https://github.com/$Repo/releases/download/$tag/RobotHub-$($tag.Substring(1)).zip"
            $size = 0
        }
        $mb = if ($size) { " ($([math]::Round($size / 1MB)) MB)" } else { "" }
        Say "Downloading$mb ..."
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -Headers @{ "User-Agent" = $headers["User-Agent"] }
        if ($digest -and $digest.StartsWith("sha256:")) {
            $got = (Get-Sha256 $dest)
            if ($got -ne $digest.Substring(7).ToLower()) { throw "The download is damaged. Run the line again." }
        }
        Done "Downloading$mb"
    }

    function New-Shortcut($path) {
        $dir = Split-Path $path -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $shell = New-Object -ComObject WScript.Shell
        $s = $shell.CreateShortcut($path)
        $s.TargetPath = Join-Path $app "runtime\pythonw.exe"
        $s.Arguments = '-I "' + (Join-Path $app "launch.pyw") + '"'
        $s.WorkingDirectory = $app
        $s.IconLocation = (Join-Path $app "robot-hub\assets\labalab.ico") + ",0"
        $s.Description = "Open LabaLab Robot Hub"
        $s.Save()
    }

    Write-Host ""
    Write-Host "  LabaLab Robot Hub installer" -ForegroundColor Yellow
    Write-Host "  Installing for this Windows user only. No admin needed."
    Write-Host ""

    # ------------------------------------------------------------ uninstall
    if ($Uninstall) {
        Stop-RobotHub
        foreach ($d in @($appNew, $app, $appOld)) { Remove-Folder $d }
        foreach ($l in $links) { if (Test-Path -LiteralPath $l) { Remove-Item -LiteralPath $l -Force } }
        Done "Removed the app and its shortcuts"
        if ($RemoveData) {
            Remove-Folder $data
            Done "Removed your keys, settings and logs"
        } elseif (Test-Path $data) {
            Say "Your keys, settings and logs stay in $data"
        }
        Remove-Folder (Join-Path $Root "download")
        if ((Test-Path $Root) -and -not (Get-ChildItem -LiteralPath $Root -Force)) { Remove-Item -LiteralPath $Root -Force }
        Write-Host ""
        return
    }

    if (-not (Test-Path $tar)) { Fail "This Windows is too old: tar.exe is missing (Windows 10 1803 or newer is needed)."; return }
    New-Item -ItemType Directory -Force -Path $Root | Out-Null

    # ------------------------------------------------------------ get the bundle
    $download = Join-Path $Root "download"
    if ($Source) {
        $Source = Get-FullPath $Source
        if (-not (Test-Path (Join-Path $Source "launch.pyw"))) { Fail "That folder is not a Robot Hub bundle: $Source"; return }
    } elseif ($Zip) {
        $Zip = Get-FullPath $Zip
        if (-not (Test-Path -LiteralPath $Zip)) { Fail "No such file: $Zip"; return }
        Done "Using $(Split-Path $Zip -Leaf)"
    } else {
        New-Item -ItemType Directory -Force -Path $download | Out-Null
        $Zip = Join-Path $download "RobotHub.zip"
        try { Get-ReleaseZip $Zip }
        catch {
            Remove-Folder $download
            if (-not (Get-ChildItem -LiteralPath $Root -Force)) { Remove-Item -LiteralPath $Root -Force }
            Fail "The download failed. Check the internet connection and run the line again."
            Write-Host "  ($($_.Exception.Message))" -ForegroundColor DarkGray
            return
        }
    }

    # ------------------------------------------------------------ unpack next to the old one
    Say "Unpacking ..."
    Remove-Folder $appNew
    New-Item -ItemType Directory -Force -Path $appNew | Out-Null
    if ($Source) {
        Copy-Item -Path (Join-Path $Source "*") -Destination $appNew -Recurse -Force
    } else {
        & $tar -x -f $Zip -C $appNew
        if ($LASTEXITCODE -ne 0) { Remove-Folder $appNew; Fail "Unpacking failed. Download it again (run the line again)."; return }
    }
    $required = @("runtime\pythonw.exe", "runtime\python.exe", "robot-hub\hub\main.py", "launch.pyw")
    foreach ($f in $required) {
        if (-not (Test-Path (Join-Path $appNew $f))) { Remove-Folder $appNew; Fail "The bundle is incomplete ($f is missing)."; return }
    }
    $version = "?"
    $vfile = Join-Path $appNew "VERSION"
    if (Test-Path $vfile) { $version = (Get-Content $vfile -Raw).Trim() }
    Done "Unpacking (version $version)"

    # ------------------------------------------------------------ swap
    Stop-RobotHub
    Remove-Folder $appOld
    if (Test-Path $app) {
        $moved = $false
        for ($i = 0; $i -lt 10 -and -not $moved; $i++) {
            try { Rename-Item -LiteralPath $app -NewName "app.old" -ErrorAction Stop; $moved = $true }
            catch { Get-OurProcesses | ForEach-Object { try { $_.Kill() } catch { } }; Start-Sleep -Seconds 1 }
        }
        if (-not $moved) { Fail "Robot Hub is still running. Close it (tray icon > Quit) and run the line again."; return }
    }
    Rename-Item -LiteralPath $appNew -NewName "app"
    New-Item -ItemType Directory -Force -Path $data | Out-Null
    if ((-not $Source) -and (Test-Path $download)) { Remove-Folder $download }

    # ------------------------------------------------------------ shortcuts
    if (-not $NoShortcuts) {
        try {
            foreach ($l in $links) { New-Shortcut $l }
            Done "Desktop shortcut"
        } catch {
            Say "Could not make the shortcuts: $($_.Exception.Message)"
        }
    }

    # ------------------------------------------------------------ open it
    if (-not $NoLaunch) {
        Start-Process -FilePath (Join-Path $app "runtime\pythonw.exe") -ArgumentList ('-I "' + (Join-Path $app "launch.pyw") + '"') -WorkingDirectory $app
        Done "Opening Robot Hub"
    }
    Write-Host ""
    Write-Host "  You can close this window." -ForegroundColor Green
    Write-Host "  Next time, double-click $name on your desktop. To update, run the same line again."
    Write-Host ""
}

try {
    Install-RobotHub -Zip $Zip -Source $Source -Root $Root -Repo $Repo -Uninstall:$Uninstall `
        -RemoveData:$RemoveData -NoLaunch:$NoLaunch -NoShortcuts:$NoShortcuts `
        -DesktopDir $DesktopDir -StartMenuDir $StartMenuDir
} catch {
    # Never `exit`: under `irm | iex` that would close the student's window.
    Write-Host ""
    Write-Host "  Robot Hub was not installed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Run the line again. If it keeps failing, show this window to the lab." -ForegroundColor Red
    Write-Host ""
    if ([Environment]::CommandLine -match '-Command') {   # started by the app: see Fail
        Write-Host "  This window closes in 60 s."; Start-Sleep -Seconds 60
    }
}

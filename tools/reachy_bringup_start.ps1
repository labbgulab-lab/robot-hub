<#
Start tools/reachy_bringup.py on its own, outside whoever called this.

The bring-up takes this laptop off its WiFi for a few minutes, so it must not
be a child of a Claude session (or of any window that might close): it is
created through WMI, which makes it a child of the WMI service, in its own
minimised window. Progress: logs\bringup\status.json and the log beside it.

    .\tools\reachy_bringup_start.ps1 -Name reachy4 -Sn 1000909... -FleetFile C:\...\FLEET.md
    .\tools\reachy_bringup_start.ps1 -Name reachy4 -Check     # preflight only -> logs\bringup\check.txt
#>
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Sn = "",
    [string]$FleetFile = "",
    # the robot's address when it is already on the hotspot ($Host is taken)
    [string]$RobotHost = "",
    [switch]$Check
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "tools\reachy_bringup.py"
$out = Join-Path $root "logs\bringup"
New-Item -ItemType Directory -Force $out | Out-Null
if ($Name -notmatch '^reachy\d+$') { throw "Name must look like reachy4" }

$call = "`"$py`" `"$script`" --name $Name"
if ($Sn) { $call += " --sn `"$Sn`"" }
if ($FleetFile) { $call += " --fleet-file `"$FleetFile`"" }
if ($RobotHost) {
    if ($RobotHost -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "RobotHost must be an IPv4 address" }
    $call += " --host $RobotHost"
}

$cmd = Join-Path $out "run-$Name.cmd"
if ($Check) {
    $lines = @("@echo off", "$call --check > `"$out\check.txt`" 2>&1")
} else {
    $lines = @("@echo off", "title Reachy set-up: $Name", "cd /d `"$root`"", $call,
               "echo.", "echo Finished. This window can be closed.", "pause >nul")
}
Set-Content -Path $cmd -Value $lines -Encoding ASCII

$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly `
    -Property @{ ShowWindow = [uint16]7 }          # minimised, no focus
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "cmd.exe /c `"$cmd`""
    CurrentDirectory = $root
    ProcessStartupInformation = $startup
}
if ($r.ReturnValue -ne 0) { throw "could not start it (WMI code $($r.ReturnValue))" }
"started pid $($r.ProcessId): $call"

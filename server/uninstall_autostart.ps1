<#
.SYNOPSIS
  Undo server\install_autostart.ps1: nothing more, nothing less.

.DESCRIPTION
  Run from an elevated PowerShell:

      powershell -NoProfile -ExecutionPolicy Bypass -File server\uninstall_autostart.ps1

  Reads %ProgramData%\StockInsights\controller\install_state.json (written by the
  installer) and reverses only what it records:

    - Stops and removes the scheduled task "StockInsights Controller". Stopping it
      ends the controller, and with it the server (it runs in the controller's job).
    - Puts the SQL Server service, and SQL Server Browser if the installer changed
      it, back to the start type they had before. Neither is stopped: SQL Server
      keeps running until the next restart of the PC.
    - Leaves the controller folder (configuration, token, logs) in place, unless
      -RemoveData is given AND the installer created it.

  Afterwards you can start the server by hand again: python server\server.py
#>
[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:ProgramData 'StockInsights\controller'),
    [switch]$RemoveData
)

$ErrorActionPreference = 'Stop'
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Note($text) { Write-Host "   $text" }
function Did($text)  { Write-Host "   $text" -ForegroundColor Green }

$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
            ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $elevated) {
    throw 'Run this from an elevated PowerShell (right-click PowerShell > Run as administrator).'
}

$statePath = Join-Path $DataRoot 'install_state.json'
if (-not (Test-Path $statePath)) {
    Write-Host "Nothing to undo: $statePath does not exist (autostart was never installed here)."
    exit 0
}
$state = Get-Content $statePath -Raw | ConvertFrom-Json

# ------------------------------------------------------------------- task
Step 'Scheduled task'
$taskName = if ($state.task_name) { $state.task_name } else { 'StockInsights Controller' }
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $taskName
        Did 'Stopped the controller (the server stopped with it).'
    }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Did "Removed the task '$taskName'."
} else { Note "No task '$taskName' (already removed)." }

# ------------------------------------------------------------- services
Step 'Services'
function Restore-StartType([string]$Name, $Previous) {
    if (-not $Previous) { Note "$Name was not changed by the installer; left as it is."; return }
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $svc) { Note "$Name no longer exists."; return }
    if ($svc.StartType -ne 'Automatic') { Note "$Name is already $($svc.StartType); left as it is."; return }
    Set-Service -Name $Name -StartupType $Previous
    Did "$Name starts $Previous again (as before the install). It keeps running for now."
}
if ($state.sql_service) { Restore-StartType $state.sql_service $state.sql_service_previous_start }
if ($state.browser_previous_start) { Restore-StartType 'SQLBrowser' $state.browser_previous_start }

# ----------------------------------------------------------------- data
Step "Controller folder $DataRoot"
if ($RemoveData -and $state.created_data_root) {
    Remove-Item -LiteralPath $DataRoot -Recurse -Force
    Did 'Removed it (configuration, token and logs).'
} else {
    Remove-Item -LiteralPath $statePath -Force
    Note 'Kept (logs and configuration stay for reference). -RemoveData deletes it if the installer created it.'
}

Write-Host "`nDone. Autostart is off. Start the server by hand with: python server\server.py" -ForegroundColor Green

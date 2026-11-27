<#
.SYNOPSIS
  Make the Stock Insights sync server (and its SQL Server) start when this PC starts.

.DESCRIPTION
  Run ONCE from an elevated PowerShell ("Run as administrator"), from the repository:

      powershell -NoProfile -ExecutionPolicy Bypass -File server\install_autostart.ps1

  Safe to run again: every step checks first and says what it did or skipped.

    1. Picks the Python that runs the server (one that can import fastapi, uvicorn
       and pyodbc) and checks server\server.py and server\.env exist (it never
       opens .env).
    2. Sets the SQL Server instance service (MSSQL$STOCKINSIGHTS, or the one it
       finds) to start automatically and starts it. SQL Server Browser too, but
       only when the instance cannot be reached through shared memory.
    3. Creates %ProgramData%\StockInsights\controller (configuration, token, logs),
       readable and writable only by you, SYSTEM and Administrators.
    4. Writes controller.json there (Python, server folder, port 8742, API port 8746).
    5. Registers the scheduled task "StockInsights Controller": at system startup,
       plus every 5 minutes as a safety net (a second copy never runs), no time
       limit, restarts on failure, starts when available.
    6. Starts the task and waits until the controller answers.

  Everything it changes is written to install_state.json in that folder, so
  server\uninstall_autostart.ps1 undoes exactly that and nothing else.

  It does not touch the Colonial controller (service ColonialController, ports
  8740-8745, C:\ProgramData\Colonial).

.PARAMETER Account
  Who the controller (and so the server) runs as.
    CurrentUser (default): your own Windows account, without storing a password
      (S4U logon). Same Python, packages and file access as when you start
      server.py by hand today. SQL Server is reached with the SQL login in
      server\.env, so no network credentials are needed.
    System: the LocalSystem account. Refused when the server's packages were
      installed with "pip install --user" (SYSTEM cannot see those).

.PARAMETER PythonExe
  The python.exe that runs the server. Default: the first of server\.venv,
  .venv and "python" on PATH that can import the server's packages.

.PARAMETER SqlService
  The SQL Server service name. Default: MSSQL$STOCKINSIGHTS, else the one
  MSSQL$* service whose name contains STOCKINSIGHTS, else the only SQL Server
  service on this PC.

.PARAMETER NoStart
  Register everything but do not start the task now.
#>
[CmdletBinding()]
param(
    [ValidateSet('CurrentUser', 'System')]
    [string]$Account   = 'CurrentUser',
    [string]$PythonExe = '',
    [string]$SqlService = '',
    [string]$TunnelService = 'cloudflared',
    [int]$Port         = 8742,
    [int]$ApiPort      = 8746,
    [string]$DataRoot  = (Join-Path $env:ProgramData 'StockInsights\controller'),
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$TaskName = 'StockInsights Controller'
$done = New-Object System.Collections.Generic.List[string]

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Note($text) { Write-Host "   $text" }
function Did($text)  { Write-Host "   $text" -ForegroundColor Green; $done.Add($text) }
# Windows PowerShell 5.1 turns a native program's stderr into a terminating error
# under ErrorActionPreference=Stop, even when redirected; run them with Continue.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & $Exe @Arguments 2>$null; return @{ Code = $LASTEXITCODE; Out = $out } }
    finally { $ErrorActionPreference = $old }
}

$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
            ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $elevated) {
    throw 'Run this from an elevated PowerShell (right-click PowerShell > Run as administrator).'
}
if ($Port -ge 8740 -and $Port -le 8745 -and $Port -ne 8742) { throw "Port $Port belongs to the Colonial servers; keep 8742." }
if ($ApiPort -ge 8740 -and $ApiPort -le 8745) { throw "API port $ApiPort belongs to the Colonial controller; use 8746." }

$repo = Split-Path -Parent $PSScriptRoot
$serverDir = Join-Path $repo 'server'
$statePath = Join-Path $DataRoot 'install_state.json'
$state = [ordered]@{}
if (Test-Path $statePath) {
    $old = Get-Content $statePath -Raw | ConvertFrom-Json
    foreach ($p in $old.PSObject.Properties) { $state[$p.Name] = $p.Value }
}
function Save-State {
    New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
    ($state | ConvertTo-Json -Depth 4) | Set-Content -Path $statePath -Encoding UTF8
}
Write-Host "Stock Insights autostart  (repository: $repo)"

# --------------------------------------------------------------- 1. Python
Step '1. Python and server files'
if (-not (Test-Path (Join-Path $serverDir 'server.py'))) { throw "No server.py in $serverDir." }
if (Test-Path (Join-Path $serverDir '.env')) {
    Note 'server\.env exists (not opened).'
} else {
    Write-Warning 'server\.env is missing: the server will exit at once. Copy .env.example to .env and fill it in first.'
}
$candidates = @()
if ($PythonExe) { $candidates = @($PythonExe) } else {
    $candidates = @((Join-Path $serverDir '.venv\Scripts\python.exe'), (Join-Path $repo '.venv\Scripts\python.exe'))
    $onPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source -notmatch 'WindowsApps') { $candidates += $onPath.Source }
}
$py = $null
foreach ($c in $candidates) {
    if (-not (Test-Path $c)) { continue }
    if ((Invoke-Native $c @('-c', 'import fastapi, uvicorn, pyodbc')).Code -eq 0) { $py = (Resolve-Path $c).Path; break }
    Note "skipped $c (cannot import fastapi, uvicorn and pyodbc)"
}
if (-not $py) { throw 'No Python here can import fastapi, uvicorn and pyodbc. Install server\requirements.txt, or pass -PythonExe.' }
Note "Python: $py ($((Invoke-Native $py @('-V')).Out))"
if ($Account -eq 'System') {
    $where = (Invoke-Native $py @('-c', 'import fastapi, pyodbc; print(fastapi.__file__); print(pyodbc.__file__)')).Out
    foreach ($w in $where) {
        if ($env:APPDATA -and $w.StartsWith($env:APPDATA, [StringComparison]::OrdinalIgnoreCase)) {
            throw "The server's packages are in your user folder ($w), which SYSTEM cannot see. Use -Account CurrentUser."
        }
    }
}

# ------------------------------------------------------------ 2. SQL Server
Step '2. SQL Server'
if (-not $SqlService) {
    if (Get-Service -Name 'MSSQL$STOCKINSIGHTS' -ErrorAction SilentlyContinue) {
        $SqlService = 'MSSQL$STOCKINSIGHTS'
    } else {
        $all = @(Get-Service -Name 'MSSQL*' -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'MSSQLSERVER' -or $_.Name -like 'MSSQL$*' })
        $named = @($all | Where-Object { $_.Name -like '*STOCKINSIGHTS*' })
        if ($named.Count -eq 1) { $SqlService = $named[0].Name }
        elseif ($all.Count -eq 1) { $SqlService = $all[0].Name; Note "MSSQL`$STOCKINSIGHTS not found; using the only SQL Server service, $SqlService." }
        else {
            $names = ($all | ForEach-Object { $_.Name }) -join ', '
            throw "Could not tell which SQL Server service the server uses (found: $names). Pass -SqlService NAME."
        }
    }
}
$svc = Get-Service -Name $SqlService -ErrorAction SilentlyContinue
if (-not $svc) { throw "Service $SqlService does not exist on this PC." }
$state['sql_service'] = $SqlService
if ($svc.StartType -ne 'Automatic') {
    if (-not $state.Contains('sql_service_previous_start')) { $state['sql_service_previous_start'] = "$($svc.StartType)" }
    Set-Service -Name $SqlService -StartupType Automatic
    Save-State
    Did "$SqlService now starts automatically (was $($svc.StartType))."
} else { Note "$SqlService already starts automatically." }
if ((Get-Service $SqlService).Status -ne 'Running') {
    Start-Service -Name $SqlService
    (Get-Service $SqlService).WaitForStatus('Running', '00:01:30')
    Did "Started $SqlService."
} else { Note "$SqlService is running." }

# SQL Server Browser: only needed when the instance cannot be reached through
# shared memory (the server connects to localhost\INSTANCE).
$instance = if ($SqlService -like 'MSSQL$*') { $SqlService.Substring(6) } else { 'MSSQLSERVER' }
$sharedMemory = $null
try {
    $id = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL' -ErrorAction Stop).$instance
    if ($id) {
        $sharedMemory = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$id\MSSQLServer\SuperSocketNetLib\Sm" -ErrorAction Stop).Enabled
    }
} catch { $sharedMemory = $null }
if ($sharedMemory -eq 1 -or $instance -eq 'MSSQLSERVER') {
    Note 'SQL Server Browser not needed (shared memory is on, or this is the default instance).'
} else {
    $browser = Get-Service -Name 'SQLBrowser' -ErrorAction SilentlyContinue
    if (-not $browser) {
        Write-Warning 'Shared memory is off and SQL Server Browser is not installed: check PORTFOLIO_SQL_SERVER names a fixed TCP port.'
    } else {
        if ($browser.StartType -ne 'Automatic') {
            if (-not $state.Contains('browser_previous_start')) { $state['browser_previous_start'] = "$($browser.StartType)" }
            Set-Service -Name 'SQLBrowser' -StartupType Automatic
            Save-State
            Did "SQL Server Browser now starts automatically (was $($browser.StartType)), because shared memory is off."
        }
        if ((Get-Service 'SQLBrowser').Status -ne 'Running') { Start-Service 'SQLBrowser'; Did 'Started SQL Server Browser.' }
    }
}

# ----------------------------------------------------------- 3. Data folder
Step "3. Controller folder $DataRoot"
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if (-not (Test-Path $DataRoot)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot 'logs') | Out-Null
    $state['created_data_root'] = $true
    Did "Created $DataRoot."
} else {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataRoot 'logs') | Out-Null
    Note 'already exists.'
}
# SYSTEM, Administrators: full. You: modify (read the token, open the logs).
& icacls $DataRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*${ownerSid}:(OI)(CI)M" /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls failed on $DataRoot" }
Note 'permissions: you, SYSTEM and Administrators only.'
Save-State

# ------------------------------------------------------------ 4. Configuration
Step '4. controller.json'
$configPath = Join-Path $DataRoot 'controller.json'
$cfg = [ordered]@{}
if (Test-Path $configPath) {
    $existing = Get-Content $configPath -Raw | ConvertFrom-Json
    foreach ($p in $existing.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
}
$cfg['python_exe'] = $py
$cfg['server_dir'] = $serverDir
$cfg['port'] = $Port
$cfg['api_port'] = $ApiPort
$cfg['autostart'] = $true
$cfg['sql_service'] = $SqlService
$cfg['tunnel_service'] = $TunnelService
$cfg['wait_for_sql'] = $true
($cfg | ConvertTo-Json -Depth 4) | Set-Content -Path $configPath -Encoding UTF8
Did "Wrote $configPath (server port $Port, API 127.0.0.1:$ApiPort)."

$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Warning "Something already listens on port $Port (process $($listening[0].OwningProcess)). If it is server.py in a window, close it: the controller waits until the port is free."
}
if (Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue) {
    Note "Port $ApiPort is in use: probably the controller from an earlier run (it is restarted below)."
}

# ---------------------------------------------------------- 5. Scheduled task
Step "5. Scheduled task '$TaskName'"
$action = New-ScheduledTaskAction -Execute $py -Argument '-X utf8 -m si_controller run' -WorkingDirectory $repo
$atBoot = New-ScheduledTaskTrigger -AtStartup
# Safety net: if the controller ever exits, this starts it again within 5 minutes.
# MultipleInstances IgnoreNew means it does nothing while the controller runs.
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
if ($Account -eq 'System') {
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $runsAs = 'SYSTEM'
} else {
    $me = "$env:USERDOMAIN\$env:USERNAME"
    $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType S4U -RunLevel Limited
    $runsAs = "$me (no password stored)"
}
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $TaskName
    Note 'stopped the running controller to update it (the server stops with it).'
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atBoot, $every5) `
    -Settings $settings -Principal $principal -Force `
    -Description 'Starts and watches the Stock Insights sync server (python -m si_controller run). Installed by server\install_autostart.ps1.' | Out-Null
$state['task_name'] = $TaskName
Save-State
if ($existingTask) { Did "Updated the task (runs as $runsAs)." } else { Did "Registered the task (runs as $runsAs, at startup and every 5 minutes if not running)." }

# ----------------------------------------------------------------- 6. Start
if (-not $NoStart) {
    Step '6. Start'
    Start-ScheduledTask -TaskName $TaskName
    $env:SI_CONTROLLER_HOME = $DataRoot
    $ok = $false
    foreach ($i in 1..30) {
        Start-Sleep -Seconds 1
        Push-Location $repo
        $result = Invoke-Native $py @('-X', 'utf8', '-m', 'si_controller', 'status')
        Pop-Location
        if ($result.Code -eq 0) { $result.Out | ForEach-Object { Note $_ }; $ok = $true; break }
    }
    if ($ok) { Did 'The controller is answering.' }
    else { Write-Warning "The controller is not answering yet. Look in $DataRoot\logs\controller.log and events.jsonl." }
}

Write-Host "`nDone. What changed:" -ForegroundColor Green
foreach ($d in $done) { Write-Host "  - $d" }
Write-Host "`nWatch it:  python -m si_manager   (or si_manager\StockInsightsServerManager.bat)"
Write-Host "Undo:      powershell -NoProfile -ExecutionPolicy Bypass -File server\uninstall_autostart.ps1"

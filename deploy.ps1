param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "init", "start", "start-bg", "stop", "restart", "status", "logs", "help")]
    [string]$Command = "help",

    [string]$Config = ""
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $RootDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PipExe = Join-Path $VenvDir "Scripts\pip.exe"
$AppFile = Join-Path $RootDir "app.py"
$DefaultConfig = Join-Path $RootDir "config.json"
$DeployDir = Join-Path $RootDir ".deploy"
$PidFile = Join-Path $DeployDir "photo-share.pid"
$LogFile = Join-Path $DeployDir "photo-share.log"
$ErrLogFile = Join-Path $DeployDir "photo-share.err.log"

if ([string]::IsNullOrWhiteSpace($Config)) {
    $Config = $DefaultConfig
}

function Show-Usage {
    Write-Host @"
Usage: .\deploy.ps1 <command> [-Config <path>]

Commands:
  install     Create .venv and install requirements
  init        Create default config.json if it does not exist
  start      Start app in foreground
  start-bg   Start app in background
  stop       Stop background app
  restart    Restart background app
  status     Show background app status
  logs       Follow background app logs

Options:
  -Config <path>  Config file path. Default: $DefaultConfig
"@
}

function Ensure-Python {
    if (Test-Path -LiteralPath $PythonExe) {
        return
    }

    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) {
        & py -3 -m venv $VenvDir
        return
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python -m venv $VenvDir
        return
    }

    throw "Python is not installed or not in PATH."
}

function Install-App {
    Ensure-Python
    & $PythonExe -m ensurepip --upgrade --default-pip | Out-Null
    & $PythonExe -m pip install --upgrade pip
    & $PipExe install -r (Join-Path $RootDir "requirements.txt")
}

function Init-Config {
    Ensure-Python
    if (Test-Path -LiteralPath $Config) {
        Write-Host "Config already exists: $Config"
        return
    }
    & $PythonExe $AppFile --config $Config
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Get-RunningProcess {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }
    $pidText = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($pidText)) {
        return $null
    }
    $processId = 0
    if (-not [int]::TryParse($pidText, [ref]$processId)) {
        return $null
    }
    return Get-Process -Id $processId -ErrorAction SilentlyContinue
}

function Start-Foreground {
    Ensure-Python
    & $PythonExe $AppFile --config $Config
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Start-Background {
    Ensure-Python
    New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
    $running = Get-RunningProcess
    if ($running) {
        Write-Host "Already running with PID $($running.Id)"
        return
    }

    $process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @($AppFile, "--config", $Config) `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrLogFile `
        -WindowStyle Hidden `
        -PassThru

    Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII
    Write-Host "Started with PID $($process.Id)"
    Write-Host "Logs: $LogFile"
    Write-Host "Error logs: $ErrLogFile"
}

function Stop-Background {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        Write-Host "Not running: PID file not found."
        return
    }

    $running = Get-RunningProcess
    if ($running) {
        Stop-Process -Id $running.Id -Force
        Write-Host "Stopped PID $($running.Id)"
    } else {
        Write-Host "Process is not running."
    }
    Remove-Item -LiteralPath $PidFile -Force
}

function Show-Status {
    $running = Get-RunningProcess
    if ($running) {
        Write-Host "Running with PID $($running.Id)"
    } else {
        Write-Host "Not running"
    }
}

function Show-Logs {
    New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
    if (-not (Test-Path -LiteralPath $LogFile)) {
        New-Item -ItemType File -Path $LogFile | Out-Null
    }
    if (-not (Test-Path -LiteralPath $ErrLogFile)) {
        New-Item -ItemType File -Path $ErrLogFile | Out-Null
    }
    Get-Content -LiteralPath $LogFile, $ErrLogFile -Wait -Tail 80
}

switch ($Command) {
    "install" { Install-App }
    "init" { Init-Config }
    "start" { Start-Foreground }
    "start-bg" { Start-Background }
    "stop" { Stop-Background }
    "restart" {
        Stop-Background
        Start-Background
    }
    "status" { Show-Status }
    "logs" { Show-Logs }
    "help" { Show-Usage }
}

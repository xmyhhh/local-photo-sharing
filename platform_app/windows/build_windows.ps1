param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$VenvDir = Join-Path $RootDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PipExe = Join-Path $VenvDir "Scripts\pip.exe"
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build"
$SpecFile = Join-Path $RootDir "platform_app\windows\photo_share_tray.spec"
$PyInstallerWorkDir = Join-Path $BuildDir "pyinstaller"

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

function Install-BuildDeps {
    Ensure-Python
    & $PythonExe -m ensurepip --upgrade --default-pip | Out-Null
    & $PythonExe -m pip install --upgrade pip
    & $PipExe install -r (Join-Path $RootDir "requirements.txt")
    & $PipExe install pyinstaller
}

function Invoke-Build {
    Install-BuildDeps
    if ($Clean) {
        if (Test-Path -LiteralPath $BuildDir) {
            Remove-Item -LiteralPath $BuildDir -Recurse -Force
        }
        if (Test-Path -LiteralPath $DistDir) {
            Remove-Item -LiteralPath $DistDir -Recurse -Force
        }
    }

    New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
    New-Item -ItemType Directory -Path $PyInstallerWorkDir -Force | Out-Null

    & $PythonExe -m PyInstaller --noconfirm --distpath $DistDir --workpath $PyInstallerWorkDir $SpecFile
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE."
    }

    Write-Host "Build completed."
    Write-Host "EXE: $(Join-Path $DistDir 'LocalPhotoSharingTray.exe')"
}

Invoke-Build

# Development environment only. Does not change the validated Tk build environment.
[CmdletBinding()]
param([string]$PythonExecutable, [string]$EnvironmentDirectory, [switch]$WithBusinessDependencies)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $sourceRoot
if (-not $EnvironmentDirectory) {
    $EnvironmentDirectory = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant\qt-dev-py39'
}
if (-not $PythonExecutable) {
    . (Join-Path $PSScriptRoot 'git_hook_python.ps1')
    $profile = Resolve-LineCheckPython -RepoRoot $repoRoot
    $PythonExecutable = $profile.executable
}
$qtPython = Join-Path $EnvironmentDirectory 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $qtPython -PathType Leaf)) {
    & $PythonExecutable -m venv $EnvironmentDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Qt independent venv creation failed' }
}
& $qtPython -m pip install --index-url https://pypi.org/simple --require-hashes -r (Join-Path $sourceRoot 'requirements-qt.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned Qt dependency installation failed' }
if ($WithBusinessDependencies) {
    & $qtPython -m pip install --index-url https://pypi.org/simple -r (Join-Path $sourceRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Original pinned project-service dependencies failed' }
}
& $qtPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Qt dependency consistency check failed' }
& $qtPython -I -c "import platform,sys;from importlib.metadata import version;from PySide6.QtCore import qVersion;assert sys.version_info[:3]==(3,9,10) and platform.architecture()[0]=='64bit';assert version('PySide6-Essentials')==version('shiboken6')=='6.8.3';print('QT_ENVIRONMENT_OK',qVersion())"
if ($LASTEXITCODE -ne 0) { throw 'Qt interpreter/version verification failed' }
Write-Output "Qt Python: $qtPython"
Write-Output "Workspace: & '$qtPython' '$(Join-Path $sourceRoot 'run_dutpilot_qt.py')'"
Write-Output "Demo: & '$qtPython' '$(Join-Path $sourceRoot 'run_dutpilot_qt.py')' --demo"

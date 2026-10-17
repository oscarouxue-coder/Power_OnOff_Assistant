param(
    [string]$BasePython = "",
    [string]$EnvironmentDirectory = (Join-Path $env:LOCALAPPDATA "LineCheckAssistant\build-env-py39")
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvironmentDirectory = [System.IO.Path]::GetFullPath($EnvironmentDirectory)
$buildPython = Join-Path $EnvironmentDirectory "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
    if (Test-Path -LiteralPath $EnvironmentDirectory) {
        throw "Refusing to reuse an existing directory without a virtual-environment Python: $EnvironmentDirectory"
    }
    $candidates = @(
        @{ Command = "py"; Arguments = @("-3.9") },
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() }
    )
    if ($BasePython) { $candidates = @(@{ Command = $BasePython; Arguments = @() }) }
    $selectedPython = ""
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $command -or $command.Source -like "*\WindowsApps\*") { continue }
        $probeArgs = $candidate.Arguments
        try {
            $found = & $command.Source @probeArgs -I -X utf8 -c "import sys,struct; sys.exit(1) if sys.version_info[:3] != (3,9,10) or struct.calcsize('P') != 8 else print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { $selectedPython = [string]($found | Select-Object -Last 1); break }
        }
        catch { continue }
    }
    if (-not $selectedPython) {
        throw "CPython 3.9.10 x64 not found. Install the Windows 64-bit installer from https://www.python.org/downloads/release/python-3910/ or pass -BasePython with its full python.exe path."
    }
    & $selectedPython -I -X utf8 -m venv $EnvironmentDirectory
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the packaging environment" }
}

& $buildPython -I -X utf8 -c "import sys; from pathlib import Path; assert sys.prefix != sys.base_prefix; assert sys.version_info[:3] == (3, 9, 10) and sys.maxsize > 2**32; assert 'include-system-site-packages = false' in (Path(sys.prefix) / 'pyvenv.cfg').read_text().lower()"
if ($LASTEXITCODE -ne 0) { throw "The packaging environment is not isolated CPython 3.9.10" }

& $buildPython -I -X utf8 -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "Unable to install the locked packaging dependencies" }
& $buildPython -I -X utf8 -m pip check
if ($LASTEXITCODE -ne 0) { throw "The packaging dependencies are inconsistent" }
& $buildPython -I -X utf8 (Join-Path $projectRoot "scripts\check_build_environment.py")
if ($LASTEXITCODE -ne 0) { throw "The packaging environment does not match the standard; use a fresh EnvironmentDirectory if extra packages were installed." }

Write-Host "Packaging Python: $buildPython"

# Shared interpreter discovery for the Windows Git hook and its installer.
# Dot-source only: this file never installs packages or changes Git settings.

function Get-LineCheckPythonProfile {
    param([string]$Executable, [string[]]$PrefixArguments = @())

    if ($Executable -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/]') {
        throw "Windows Store placeholder: $Executable"
    }
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Interpreter file not found: $Executable"
    }
    $probe = "import json,sys,struct,platform; print(json.dumps(dict(executable=sys.executable,version=platform.python_version(),bits=struct.calcsize('P')*8,implementation=platform.python_implementation())))"
    # Both legacy py.exe and the install manager can install missing runtimes.
    # Disable their opt-ins for this probe, then restore the caller's settings.
    # https://docs.python.org/3/using/windows.html#python-manager-automatic-install
    $savedInstallSettings = @{}
    foreach ($name in @('PYLAUNCHER_ALLOW_INSTALL', 'PYLAUNCHER_ALWAYS_INSTALL', 'PYTHON_MANAGER_AUTOMATIC_INSTALL')) {
        $savedInstallSettings[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
        $env:PYLAUNCHER_ALLOW_INSTALL = $null
        $env:PYLAUNCHER_ALWAYS_INSTALL = $null
        $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = 'false'
        $output = & $Executable @PrefixArguments -I -X utf8 -c $probe 2>$null
        $probeExit = $LASTEXITCODE
    }
    finally {
        foreach ($name in $savedInstallSettings.Keys) {
            [Environment]::SetEnvironmentVariable($name, $savedInstallSettings[$name], 'Process')
        }
    }
    if ($probeExit -ne 0) { throw "Interpreter probe failed: $Executable" }
    $profile = ($output -join "`n") | ConvertFrom-Json -ErrorAction Stop
    if ($profile.implementation -ne 'CPython' -or $profile.version -ne '3.9.10' -or $profile.bits -ne 64) {
        throw "Requires CPython 3.9.10 x64; found $($profile.implementation) $($profile.version) $($profile.bits)-bit: $Executable"
    }
    if (-not $profile.executable -or -not [IO.Path]::IsPathRooted($profile.executable)) {
        throw "Interpreter probe did not return an absolute executable path: $Executable"
    }
    if ($profile.executable -match '(?i)[\\/]Microsoft[\\/]WindowsApps[\\/]' -or
        -not (Test-Path -LiteralPath $profile.executable -PathType Leaf)) {
        throw "Resolved interpreter is unavailable: $($profile.executable)"
    }
    # A launcher such as py.exe must yield an interpreter that works directly.
    if ($PrefixArguments.Count -gt 0 -or
        [IO.Path]::GetFullPath($Executable) -ne [IO.Path]::GetFullPath($profile.executable)) {
        return Get-LineCheckPythonProfile -Executable $profile.executable
    }
    return $profile
}

function Resolve-LineCheckPython {
    param([string]$RepoRoot)

    $configured = & git -C $RepoRoot config --local --get linecheck.pythonExecutable
    $configExit = $LASTEXITCODE
    if ($configExit -notin @(0, 1)) { throw 'Unable to read repository Python configuration.' }
    if ($configExit -eq 0) {
        try {
            if (-not $configured -or @($configured).Count -ne 1) { throw 'Expected one non-empty executable path.' }
            $explicitPath = [string]$configured
            if (-not [IO.Path]::IsPathRooted($explicitPath)) { $explicitPath = Join-Path $RepoRoot $explicitPath }
            return Get-LineCheckPythonProfile -Executable $explicitPath
        }
        catch {
            throw "Invalid linecheck.pythonExecutable: $($_.Exception.Message)`nCorrect it with install_git_hooks.ps1 -PythonExecutable <path>, or restore automatic discovery with: git config --local --unset linecheck.pythonExecutable"
        }
    }

    $candidates = @()
    if ($env:VIRTUAL_ENV) { $candidates += Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe' }
    $candidates += Join-Path $RepoRoot '.venv\Scripts\python.exe'
    $candidates += Join-Path $RepoRoot 'Cheating_machine_execution_tool\.venv\Scripts\python.exe'
    if ($env:LOCALAPPDATA) { $candidates += Join-Path $env:LOCALAPPDATA 'LineCheckAssistant\build-env-py39\Scripts\python.exe' }

    $failures = @()
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try { return Get-LineCheckPythonProfile -Executable $candidate }
        catch { $failures += $_.Exception.Message }
    }
    foreach ($command in @(Get-Command py -All -CommandType Application -ErrorAction SilentlyContinue)) {
        try { return Get-LineCheckPythonProfile -Executable $command.Source -PrefixArguments @('-3.9') }
        catch { $failures += $_.Exception.Message }
    }
    foreach ($name in @('python', 'python3')) {
        foreach ($command in @(Get-Command $name -All -CommandType Application -ErrorAction SilentlyContinue)) {
            try { return Get-LineCheckPythonProfile -Executable $command.Source }
            catch { $failures += $_.Exception.Message }
        }
    }
    throw ("No usable CPython 3.9.10 x64 was found. Git commit is blocked.`n" +
        "Install CPython 3.9.10 x64 with the project's dependencies (see root README.md), or configure an existing environment:`n" +
        'powershell -NoProfile -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\install_git_hooks.ps1 -PythonExecutable "C:\path\to\python.exe"' +
        "`nNo Python or packages were installed automatically.`n" + ($failures -join "`n"))
}

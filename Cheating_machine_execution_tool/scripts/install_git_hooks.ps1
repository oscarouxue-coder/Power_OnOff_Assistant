<#
.SYNOPSIS
Enable the repository's versioned Git pre-commit baseline gate.

.DESCRIPTION
Sets this repository's core.hooksPath to the root .githooks directory. After
installation, every git commit runs scripts/verify_baseline.py before Git
creates the commit.
An optional -PythonExecutable validates CPython 3.9.10 x64 and saves its path
in this repository's local Git config. Without it, existing settings are kept
and the hook discovers an interpreter automatically when no override is set.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\install_git_hooks.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\install_git_hooks.ps1 -PythonExecutable "C:\my-python\python.exe"
#>
[CmdletBinding()]
param([string]$PythonExecutable)

$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $PSCommandPath
$sourceRoot = Split-Path -Parent $scriptRoot
$repoRoot = Split-Path -Parent $sourceRoot
$hookDirectory = Join-Path $repoRoot '.githooks'
$preCommitHook = Join-Path $hookDirectory 'pre-commit'

if (-not (Test-Path -LiteralPath $preCommitHook)) {
    throw "Versioned pre-commit hook not found: $preCommitHook"
}

Push-Location -LiteralPath $repoRoot
try {
    if ($PSBoundParameters.ContainsKey('PythonExecutable')) {
        if (-not $PythonExecutable) { throw 'PythonExecutable must be a non-empty interpreter path.' }
        . (Join-Path $scriptRoot 'git_hook_python.ps1')
        $profile = Get-LineCheckPythonProfile -Executable $PythonExecutable
        & git config --local linecheck.pythonExecutable $profile.executable
        if ($LASTEXITCODE -ne 0) { throw 'Unable to save repository Python configuration.' }
        Write-Host "Repository Python: $($profile.executable) (CPython 3.9.10 x64)"
    }
    & git config core.hooksPath .githooks
    if ($LASTEXITCODE -ne 0) {
        throw 'git config core.hooksPath failed.'
    }
    Write-Host "Baseline pre-commit hook enabled: $hookDirectory"
}
finally {
    Pop-Location
}

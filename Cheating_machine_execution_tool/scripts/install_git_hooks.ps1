<#
.SYNOPSIS
Enable the repository's versioned Git pre-commit baseline gate.

.DESCRIPTION
Sets this repository's core.hooksPath to the root .githooks directory. After
installation, every git commit runs scripts/verify_baseline.py before Git
creates the commit.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\Cheating_machine_execution_tool\scripts\install_git_hooks.ps1
#>
[CmdletBinding()]
param()

$scriptRoot = Split-Path -Parent $PSCommandPath
$sourceRoot = Split-Path -Parent $scriptRoot
$repoRoot = Split-Path -Parent $sourceRoot
$hookDirectory = Join-Path $repoRoot '.githooks'
$preCommitHook = Join-Path $hookDirectory 'pre-commit'

if (-not (Test-Path -LiteralPath $preCommitHook)) {
    throw "Versioned pre-commit hook not found: $preCommitHook"
}

Push-Location $repoRoot
try {
    & git config core.hooksPath .githooks
    if ($LASTEXITCODE -ne 0) {
        throw 'git config core.hooksPath failed.'
    }
    Write-Host "Baseline pre-commit hook enabled: $hookDirectory"
}
finally {
    Pop-Location
}

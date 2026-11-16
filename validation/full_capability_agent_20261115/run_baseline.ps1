$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$sourceRoot = Join-Path $repositoryRoot 'Cheating_machine_execution_tool'
$python = Join-Path $env:LOCALAPPDATA 'LineCheckAssistant\build-env-py39\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
& $python (Join-Path $PSScriptRoot 'source_snapshot.py') (Join-Path $PSScriptRoot 'source_before.json')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location $sourceRoot
try {
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/run_git_pre_commit.ps1 2>&1 | Tee-Object -FilePath (Join-Path $PSScriptRoot 'full_baseline.log')
    $baselineExit = $LASTEXITCODE
} finally {
    Pop-Location
}
& $python (Join-Path $PSScriptRoot 'source_snapshot.py') (Join-Path $PSScriptRoot 'source_after.json') --compare (Join-Path $PSScriptRoot 'source_before.json')
$snapshotExit = $LASTEXITCODE
if ($baselineExit -ne 0) { exit $baselineExit }
exit $snapshotExit

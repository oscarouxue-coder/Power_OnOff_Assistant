# Run the unchanged baseline with one validated interpreter, without retries.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $sourceRoot

try {
    . (Join-Path $PSScriptRoot 'git_hook_python.ps1')
    $profile = Resolve-LineCheckPython -RepoRoot $repoRoot
    Write-Host "Git baseline Python: $($profile.executable) ($($profile.implementation) $($profile.version), $($profile.bits)-bit)"
    Push-Location -LiteralPath $sourceRoot
    try {
        # Keep subprocess output readable in Git/editor consoles.
        $env:PYTHONUTF8 = '1'
        $env:PYTHONIOENCODING = 'utf-8'
        # Windows/Git may supply temp directories as 8.3 aliases. Use full spelling
        # within this hook process so subprocess cwd checks compare consistently.
        foreach ($name in @('TMPDIR', 'TEMP', 'TMP')) {
            $directory = [Environment]::GetEnvironmentVariable($name, 'Process')
            if ($directory -and (Test-Path -LiteralPath $directory -PathType Container)) {
                [Environment]::SetEnvironmentVariable($name, (Get-Item -LiteralPath $directory).FullName, 'Process')
            }
        }
        & $profile.executable -X utf8 scripts/verify_baseline.py
        $baselineExit = $LASTEXITCODE
    }
    finally { Pop-Location }
    exit $baselineExit
}
catch {
    [Console]::Error.WriteLine("Git baseline: $($_.Exception.Message)")
    exit 1
}

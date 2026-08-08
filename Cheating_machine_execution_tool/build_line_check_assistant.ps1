$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$specDir = Join-Path $projectRoot "line_check_assistant\packaging_specs"
$hookDir = Join-Path $projectRoot "line_check_assistant\packaging_hooks"
$buildDir = Join-Path $projectRoot "build"
$distDir = Join-Path $projectRoot "dist"
$thirdPartyNotice = Join-Path $projectRoot "THIRD_PARTY_NOTICES.md"

New-Item -ItemType Directory -Force -Path $specDir | Out-Null

Push-Location $projectRoot
try {
    python -m PyInstaller `
        --onefile `
        --windowed `
        --noconfirm `
        --name LineCheckAssistant `
        --specpath $specDir `
        --additional-hooks-dir $hookDir `
        --paths .\Auto_power_on_off_tool `
        --collect-submodules tftpy `
        --collect-submodules openpyxl `
        --collect-submodules xlrd `
        --hidden-import requests_toolbelt.adapters.source `
        --hidden-import paramiko `
        --hidden-import ping3 `
        --hidden-import pywifi `
        --hidden-import configobj `
        --hidden-import psutil `
        --hidden-import test_case.powe_on_off_telnet `
        --hidden-import test_case.power_on_off_ssh `
        .\run_line_check_assistant.py

    if (Test-Path -LiteralPath $thirdPartyNotice) {
        Copy-Item -LiteralPath $thirdPartyNotice -Destination (Join-Path $distDir "THIRD_PARTY_NOTICES.md") -Force
    }

    $resolvedProjectRoot = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
    $resolvedBuildDir = [System.IO.Path]::GetFullPath($buildDir).TrimEnd('\')
    if ($resolvedBuildDir.StartsWith($resolvedProjectRoot + "\", [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path $resolvedBuildDir)) {
        Remove-Item -LiteralPath $resolvedBuildDir -Recurse -Force
    }
}
finally {
    Pop-Location
}

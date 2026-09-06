$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$specDir = Join-Path $projectRoot "line_check_assistant\packaging_specs"
$hookDir = Join-Path $projectRoot "line_check_assistant\packaging_hooks"
$buildDir = Join-Path $projectRoot "build"
$distDir = Join-Path $projectRoot "dist"
$thirdPartyNotice = Join-Path $projectRoot "THIRD_PARTY_NOTICES.md"
$portableConfigScript = Join-Path $projectRoot "scripts\create_portable_config.py"
$portableReadme = Join-Path $projectRoot "line_check_assistant\packaging_assets\PORTABLE_README.txt"
$versionInfo = Join-Path $projectRoot "line_check_assistant\packaging_assets\VERSION_INFO.txt"
$applicationIcon = Join-Path $projectRoot "assets\icons\line_check_assistant_network_topology_v1.ico"
$runtimeConfigDir = Join-Path $projectRoot "Auto_power_on_off_tool\config"
$exePath = Join-Path $distDir "LineCheckAssistant.exe"
$portableDir = Join-Path $distDir "LineCheckAssistant_portable"
$portableConfigDir = Join-Path $portableDir "Auto_power_on_off_tool\config"
$portableZip = Join-Path $distDir "LineCheckAssistant_portable.zip"

New-Item -ItemType Directory -Force -Path $specDir | Out-Null

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $applicationIcon -PathType Leaf)) {
        throw "Application icon is missing: $applicationIcon"
    }

    python -m PyInstaller `
        --onefile `
        --windowed `
        --noconfirm `
        --name LineCheckAssistant `
        --icon $applicationIcon `
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
        --add-data "$versionInfo;." `
        --hidden-import test_case.powe_on_off_telnet `
        --hidden-import test_case.power_on_off_ssh `
        .\run_line_check_assistant.py

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "PyInstaller did not create the expected file: $exePath"
    }

    # pyi_rth__tkinter requires these exact roots below sys._MEIPASS.  Check
    # the one-file archive itself so a build with misplaced Tcl/Tk data can
    # never be promoted to the portable ZIP again.
    $archiveListing = & python -m PyInstaller.utils.cliutils.archive_viewer -l $exePath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the PyInstaller archive, exit code $LASTEXITCODE"
    }
    # archive_viewer renders path separators escaped in repr form (\\).
    $hasTclData = [bool]($archiveListing | Select-String -SimpleMatch "'tcl\\init.tcl'")
    $hasTkData = [bool]($archiveListing | Select-String -SimpleMatch "'tk\\tk.tcl'")
    if (-not ($hasTclData -and $hasTkData)) {
        throw "Frozen Tkinter data is incomplete: expected tcl\init.tcl and tk\tk.tcl"
    }

    if (Test-Path -LiteralPath $thirdPartyNotice) {
        Copy-Item -LiteralPath $thirdPartyNotice -Destination (Join-Path $distDir "THIRD_PARTY_NOTICES.md") -Force
    }

    $resolvedDistDir = [System.IO.Path]::GetFullPath($distDir).TrimEnd('\')
    $resolvedPortableDir = [System.IO.Path]::GetFullPath($portableDir).TrimEnd('\')
    $resolvedPortableZip = [System.IO.Path]::GetFullPath($portableZip)
    if (-not $resolvedPortableDir.StartsWith($resolvedDistDir + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a portable directory outside dist: $resolvedPortableDir"
    }
    if (-not $resolvedPortableZip.StartsWith($resolvedDistDir + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a portable archive outside dist: $resolvedPortableZip"
    }

    if (Test-Path -LiteralPath $portableDir) {
        Remove-Item -LiteralPath $portableDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $portableZip) {
        Remove-Item -LiteralPath $portableZip -Force
    }

    New-Item -ItemType Directory -Force -Path $portableDir | Out-Null
    Copy-Item -LiteralPath $exePath -Destination (Join-Path $portableDir "LineCheckAssistant.exe") -Force
    Copy-Item -LiteralPath $portableReadme -Destination (Join-Path $portableDir "PORTABLE_README.txt") -Force
    if (-not (Test-Path -LiteralPath $versionInfo -PathType Leaf)) {
        throw "Portable version information is missing: $versionInfo"
    }
    Copy-Item -LiteralPath $versionInfo -Destination (Join-Path $portableDir "VERSION_INFO.txt") -Force
    if (Test-Path -LiteralPath $thirdPartyNotice) {
        Copy-Item -LiteralPath $thirdPartyNotice -Destination (Join-Path $portableDir "THIRD_PARTY_NOTICES.md") -Force
    }

    python $portableConfigScript --source $runtimeConfigDir --destination $portableConfigDir
    if ($LASTEXITCODE -ne 0) {
        throw "Portable configuration generation failed with exit code $LASTEXITCODE"
    }

    $portableExe = Join-Path $portableDir "LineCheckAssistant.exe"
    $exeHash = (Get-FileHash -LiteralPath $portableExe -Algorithm SHA256).Hash
    Set-Content `
        -LiteralPath (Join-Path $portableDir "LineCheckAssistant.exe.sha256.txt") `
        -Value "$exeHash *LineCheckAssistant.exe" `
        -Encoding Ascii

    Compress-Archive -LiteralPath $portableDir -DestinationPath $portableZip -CompressionLevel Optimal
    if (-not (Test-Path -LiteralPath $portableZip -PathType Leaf)) {
        throw "Portable archive was not created: $portableZip"
    }

    Write-Host "Single-file EXE: $exePath"
    Write-Host "Portable directory: $portableDir"
    Write-Host "Portable ZIP: $portableZip"

    $resolvedProjectRoot = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
    $resolvedBuildDir = [System.IO.Path]::GetFullPath($buildDir).TrimEnd('\')
    if ($resolvedBuildDir.StartsWith($resolvedProjectRoot + "\", [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path $resolvedBuildDir)) {
        Remove-Item -LiteralPath $resolvedBuildDir -Recurse -Force
    }
}
finally {
    Pop-Location
}

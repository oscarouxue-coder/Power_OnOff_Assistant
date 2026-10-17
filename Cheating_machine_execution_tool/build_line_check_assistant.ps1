param(
    [string]$PythonExecutable = (Join-Path $env:LOCALAPPDATA "LineCheckAssistant\build-env-py39\Scripts\python.exe"),
    [string]$OutputDirectory = "",
    [string]$WorkDirectory = "",
    [string]$BasePython = "",
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$specPath = Join-Path $projectRoot "line_check_assistant\packaging_specs\LineCheckAssistant.spec"
$buildDir = Join-Path $projectRoot "build"
$distDir = Join-Path $projectRoot "dist"
if ($WorkDirectory) { $buildDir = if ([System.IO.Path]::IsPathRooted($WorkDirectory)) { $WorkDirectory } else { Join-Path $projectRoot $WorkDirectory } }
if ($OutputDirectory) { $distDir = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) { $OutputDirectory } else { Join-Path $projectRoot $OutputDirectory } }
$allowedBuildRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build")).TrimEnd('\')
$allowedDistRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "dist")).TrimEnd('\')
$buildDir = [System.IO.Path]::GetFullPath($buildDir).TrimEnd('\')
$distDir = [System.IO.Path]::GetFullPath($distDir).TrimEnd('\')
if ($buildDir -ne $allowedBuildRoot -and -not $buildDir.StartsWith($allowedBuildRoot + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "WorkDirectory must stay within the project's build directory: $buildDir"
}
if ($distDir -ne $allowedDistRoot -and -not $distDir.StartsWith($allowedDistRoot + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must stay within the project's dist directory: $distDir"
}
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
$portableZipChecksum = Join-Path $distDir "LineCheckAssistant_portable.zip.sha256.txt"
$packageVerifier = Join-Path $projectRoot "scripts\verify_slim_package.py"
$buildInfo = Join-Path $buildDir "LineCheckAssistant\BUILD_INFO.txt"

$savedPythonPath = $env:PYTHONPATH
$savedPythonHome = $env:PYTHONHOME
$savedPythonUtf8 = $env:PYTHONUTF8

Push-Location $projectRoot
try {
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    $env:PYTHONUTF8 = "1"
    $environmentDirectory = Split-Path -Parent (Split-Path -Parent $PythonExecutable)
    & (Join-Path $projectRoot "scripts\prepare_build_environment.ps1") -BasePython $BasePython -EnvironmentDirectory $environmentDirectory
    if ($LASTEXITCODE -ne 0) { throw "Unable to prepare the standard packaging environment" }
    $profileJson = & $PythonExecutable -I -X utf8 (Join-Path $projectRoot "scripts\check_build_environment.py") --json
    if ($LASTEXITCODE -ne 0) { throw "Packaging environment verification failed" }
    $profile = ($profileJson -join "`n") | ConvertFrom-Json
    $auditArgs = @()
    foreach ($module in $profile.excluded_modules) { $auditArgs += @("--exclude", $module) }
    & $PythonExecutable -I -X utf8 (Join-Path $projectRoot "scripts\verify_baseline.py")
    if ($LASTEXITCODE -ne 0) { throw "Baseline failed; packaging is blocked" }
    if ($CheckOnly) {
        Write-Host "STANDARD_BUILD_CHECK_OK: environment and baseline passed; no EXE was built or launched."
        return
    }
    if (-not (Test-Path -LiteralPath $applicationIcon -PathType Leaf)) {
        throw "Application icon is missing: $applicationIcon"
    }

    & $PythonExecutable -I -X utf8 -m PyInstaller `
        --noconfirm `
        --workpath $buildDir `
        --distpath $distDir `
        $specPath

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "PyInstaller did not create the expected file: $exePath"
    }

    # Keep the accepted 5.x roots and the current 6.x roots below sys._MEIPASS. Check
    # the one-file archive itself so a build with misplaced Tcl/Tk data can
    # never be promoted to the portable ZIP again.
    $archiveListing = & $PythonExecutable -I -X utf8 -m PyInstaller.utils.cliutils.archive_viewer -l $exePath 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the PyInstaller archive, exit code $LASTEXITCODE"
    }
    # archive_viewer renders path separators escaped in repr form (\\).
    $hasTclData = [bool]($archiveListing | Select-String -SimpleMatch "'tcl\\init.tcl'")
    $hasTkData = [bool]($archiveListing | Select-String -SimpleMatch "'tk\\tk.tcl'")
    $hasModernTclData = [bool]($archiveListing | Select-String -SimpleMatch "'_tcl_data\\init.tcl'")
    $hasModernTkData = [bool]($archiveListing | Select-String -SimpleMatch "'_tk_data\\tk.tcl'")
    if (-not ($hasTclData -and $hasTkData -and $hasModernTclData -and $hasModernTkData)) {
        throw "Frozen Tkinter data is incomplete: expected tcl/tk and _tcl_data/_tk_data roots"
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
    Copy-Item -LiteralPath $buildInfo -Destination (Join-Path $portableDir "BUILD_INFO.txt") -Force
    if (Test-Path -LiteralPath $thirdPartyNotice) {
        Copy-Item -LiteralPath $thirdPartyNotice -Destination (Join-Path $portableDir "THIRD_PARTY_NOTICES.md") -Force
    }

    & $PythonExecutable -I -X utf8 $portableConfigScript --source $runtimeConfigDir --destination $portableConfigDir
    if ($LASTEXITCODE -ne 0) {
        throw "Portable configuration generation failed with exit code $LASTEXITCODE"
    }

    $portableExe = Join-Path $portableDir "LineCheckAssistant.exe"
    $exeHash = (Get-FileHash -LiteralPath $portableExe -Algorithm SHA256).Hash
    Set-Content `
        -LiteralPath (Join-Path $portableDir "LineCheckAssistant.exe.sha256.txt") `
        -Value "$exeHash *LineCheckAssistant.exe" `
        -Encoding Ascii
    Copy-Item -LiteralPath (Join-Path $portableDir "LineCheckAssistant.exe.sha256.txt") -Destination $distDir -Force
    Copy-Item -LiteralPath $versionInfo -Destination $distDir -Force
    Copy-Item -LiteralPath $buildInfo -Destination $distDir -Force

    Compress-Archive -LiteralPath $portableDir -DestinationPath $portableZip -CompressionLevel Optimal
    if (-not (Test-Path -LiteralPath $portableZip -PathType Leaf)) {
        throw "Portable archive was not created: $portableZip"
    }
    $zipHash = (Get-FileHash -LiteralPath $portableZip -Algorithm SHA256).Hash
    Set-Content `
        -LiteralPath $portableZipChecksum `
        -Value "$zipHash *LineCheckAssistant_portable.zip" `
        -Encoding Ascii

    & $PythonExecutable -I -X utf8 $packageVerifier --exe $exePath --zip $portableZip @auditArgs
    if ($LASTEXITCODE -ne 0) { throw "Package archive verification failed" }

    Write-Host "Single-file EXE: $exePath"
    Write-Host "Portable directory: $portableDir"
    Write-Host "Portable ZIP: $portableZip"
    Write-Host "Portable ZIP SHA256: $portableZipChecksum"

    $resolvedBuildDir = [System.IO.Path]::GetFullPath($buildDir).TrimEnd('\')
    if (($resolvedBuildDir -eq $allowedBuildRoot -or $resolvedBuildDir.StartsWith($allowedBuildRoot + "\", [System.StringComparison]::OrdinalIgnoreCase)) -and (Test-Path -LiteralPath $resolvedBuildDir)) {
        Remove-Item -LiteralPath $resolvedBuildDir -Recurse -Force
    }
}
finally {
    $env:PYTHONPATH = $savedPythonPath
    $env:PYTHONHOME = $savedPythonHome
    $env:PYTHONUTF8 = $savedPythonUtf8
    Pop-Location
}

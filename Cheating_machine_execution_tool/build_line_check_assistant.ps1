param(
    [string]$PythonExecutable = "",
    [string]$OutputDirectory = "",
    [string]$WorkDirectory = "",
    [string]$BasePython = "",
    [switch]$CheckOnly,
    [ValidateSet("Tk", "Qt")][string]$Gui = "Qt"
)

$ErrorActionPreference = "Stop"

if ($Gui -eq "Tk") {
    throw "The Tk build has been retired. Run this script without -Gui to build the Qt workspace."
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$specPath = Join-Path $projectRoot "line_check_assistant\packaging_specs\DUTPilotQt.spec"
$buildId = (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$buildDir = Join-Path $projectRoot "build\qt-$buildId"
$distDir = Join-Path $projectRoot "dist\qt-$buildId"
if (-not $PythonExecutable) {
    $PythonExecutable = Join-Path $env:LOCALAPPDATA "LineCheckAssistant\qt-build-py39\Scripts\python.exe"
}
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
if (-not $CheckOnly) {
    if ($buildDir -eq $allowedBuildRoot -or $distDir -eq $allowedDistRoot) {
        throw "Use separate build and dist subdirectories for the Qt package"
    }
    foreach ($directory in @($buildDir, $distDir)) {
        if (Test-Path -LiteralPath $directory) { throw "The Qt build requires fresh output directories: $directory" }
        $parent = Split-Path -Parent $directory
        while ($parent -and $parent.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            $item = Get-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue
            if ($item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
                throw "The Qt build output cannot traverse a junction: $parent"
            }
            $parent = Split-Path -Parent $parent
        }
    }
}
$thirdPartyNotice = Join-Path $projectRoot "THIRD_PARTY_NOTICES.md"
$portableConfigScript = Join-Path $projectRoot "scripts\create_portable_config.py"
$versionInfo = Join-Path $projectRoot "line_check_assistant\packaging_assets\QT_VERSION_INFO.txt"
$applicationIcon = Join-Path $projectRoot "assets\icons\line_check_assistant_network_topology_v1.ico"
$runtimeConfigDir = Join-Path $projectRoot "Auto_power_on_off_tool\config"
$portableDir = Join-Path $distDir "DUTPilot_portable"
$exePath = Join-Path $portableDir "DUTPilot.exe"
$portableConfigDir = Join-Path $portableDir "Auto_power_on_off_tool\config"
$portableZip = Join-Path $distDir "DUTPilot_portable.zip"
$portableZipChecksum = Join-Path $distDir "DUTPilot_portable.zip.sha256.txt"
$packageVerifier = Join-Path $projectRoot "scripts\verify_slim_package.py"
$buildInfo = Join-Path $buildDir "DUTPilotQt\BUILD_INFO.txt"
$caseSnapshot = Join-Path $buildDir "CONFIRMED_CASES.json"
$savedPythonPath = $env:PYTHONPATH
$savedPythonHome = $env:PYTHONHOME
$savedPythonUtf8 = $env:PYTHONUTF8
$savedCaseSnapshot = $env:LINECHECK_CASE_SNAPSHOT

Push-Location $projectRoot
try {
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    $env:PYTHONUTF8 = "1"
    $environmentDirectory = Split-Path -Parent (Split-Path -Parent $PythonExecutable)
    & (Join-Path $projectRoot "scripts\prepare_build_environment.ps1") -BasePython $BasePython -EnvironmentDirectory $environmentDirectory -Gui $Gui
    if ($LASTEXITCODE -ne 0) { throw "Unable to prepare the standard packaging environment" }
    $profileJson = & $PythonExecutable -I -X utf8 (Join-Path $projectRoot "scripts\check_build_environment.py") --json --gui $Gui
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

    & $PythonExecutable -I -X utf8 (Join-Path $projectRoot "scripts\export_ai_cases.py") --output $caseSnapshot
    if ($LASTEXITCODE -ne 0) { throw "Confirmed case snapshot export failed; packaging is blocked" }
    $env:LINECHECK_CASE_SNAPSHOT = $caseSnapshot

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

    Copy-Item -LiteralPath $versionInfo -Destination (Join-Path $portableDir "PORTABLE_README.txt") -Force
    if (-not (Test-Path -LiteralPath $versionInfo -PathType Leaf)) {
        throw "Portable version information is missing: $versionInfo"
    }
    Copy-Item -LiteralPath $versionInfo -Destination (Join-Path $portableDir "VERSION_INFO.txt") -Force
    Copy-Item -LiteralPath $buildInfo -Destination (Join-Path $portableDir "BUILD_INFO.txt") -Force
    Copy-Item -LiteralPath $caseSnapshot -Destination (Join-Path $portableDir "CONFIRMED_CASES.json") -Force
    if (Test-Path -LiteralPath $thirdPartyNotice) {
        Copy-Item -LiteralPath $thirdPartyNotice -Destination (Join-Path $portableDir "THIRD_PARTY_NOTICES.md") -Force
    }

    & $PythonExecutable -I -X utf8 $portableConfigScript --source $runtimeConfigDir --destination $portableConfigDir
    if ($LASTEXITCODE -ne 0) {
        throw "Portable configuration generation failed with exit code $LASTEXITCODE"
    }

    $portableExe = Join-Path $portableDir "DUTPilot.exe"
    $exeHash = (Get-FileHash -LiteralPath $portableExe -Algorithm SHA256).Hash
    Set-Content `
        -LiteralPath (Join-Path $portableDir "DUTPilot.exe.sha256.txt") `
        -Value "$exeHash *DUTPilot.exe" `
        -Encoding Ascii
    Copy-Item -LiteralPath (Join-Path $portableDir "DUTPilot.exe.sha256.txt") -Destination $distDir -Force
    Copy-Item -LiteralPath $versionInfo -Destination (Join-Path $distDir "VERSION_INFO.txt") -Force
    Copy-Item -LiteralPath $buildInfo -Destination $distDir -Force

    $pendingZip = "$portableZip.pending"
    try {
        & $PythonExecutable -I -X utf8 -m zipfile -c $pendingZip $portableDir
        if ($LASTEXITCODE -ne 0) { throw "Unable to archive the Qt portable directory" }
        Move-Item -LiteralPath $pendingZip -Destination $portableZip
    } finally {
        if (Test-Path -LiteralPath $pendingZip) { Remove-Item -LiteralPath $pendingZip -Force }
    }
    if (-not (Test-Path -LiteralPath $portableZip -PathType Leaf)) {
        throw "Portable archive was not created: $portableZip"
    }
    $zipHash = (Get-FileHash -LiteralPath $portableZip -Algorithm SHA256).Hash
    Set-Content `
        -LiteralPath $portableZipChecksum `
        -Value "$zipHash *DUTPilot_portable.zip" `
        -Encoding Ascii

    & $PythonExecutable -I -X utf8 $packageVerifier --gui $Gui --exe $exePath --zip $portableZip --case-snapshot $caseSnapshot @auditArgs
    if ($LASTEXITCODE -ne 0) { throw "Package archive verification failed" }

    Write-Host "Local build artifacts (retained for verification): $distDir"
    Write-Host "  Qt EXE: $exePath"
    Write-Host "GitHub Release attachments (upload only these two files from this build):"
    Write-Host "  Portable ZIP: $portableZip"
    Write-Host "  Portable ZIP SHA256: $portableZipChecksum"
}
finally {
    $env:PYTHONPATH = $savedPythonPath
    $env:PYTHONHOME = $savedPythonHome
    $env:PYTHONUTF8 = $savedPythonUtf8
    $env:LINECHECK_CASE_SNAPSHOT = $savedCaseSnapshot
    Pop-Location
}

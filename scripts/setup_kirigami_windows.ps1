param(
    [string]$CraftRoot = "C:\CraftRoot",
    [switch]$InstallRuntime,
    [switch]$RepairSettings
)

$ErrorActionPreference = "Stop"

Write-Host "Shinar KDE Kirigami Windows setup" -ForegroundColor Cyan

function Require-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name not found. $Hint"
    }
}

Require-Command "uv" "Install uv before running this script."

$pythonExe = "python"
$pythonArgs = @()
Require-Command "python" "Install Python 3.12 or 3.13 and disable the Microsoft Store App Execution Alias."
$pythonVersion = (& $pythonExe @pythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($pythonVersion -eq "3.14" -and (Get-Command py -ErrorAction SilentlyContinue)) {
    $supported = (& py -3.12 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
    if ($supported -eq "3.12") {
        $pythonExe = "py"
        $pythonArgs = @("-3.12")
        $pythonVersion = $supported
    }
}
Write-Host "Python detected: $pythonVersion"
if ($pythonVersion -notin @("3.12", "3.13")) {
    Write-Warning "KDE Craft officially recommends Python 3.12 or 3.13 for its bootstrap. Keep this Python for Shinar, but install a separate supported Python for Craft."
}

$craftEnv = @(
    (Join-Path $CraftRoot "craft\craftenv.ps1"),
    (Join-Path $CraftRoot "craft-tmp\craftenv.ps1")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $craftEnv) {
    Write-Host "Craft is not installed at $CraftRoot."
    Write-Host "Install it from an elevated Windows PowerShell with the official KDE bootstrap:" -ForegroundColor Yellow
    Write-Host "  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"
    Write-Host "  iex ((New-Object Net.WebClient).DownloadString('https://invent.kde.org/packaging/craft/-/raw/master/setup/install_craft.ps1'))"
    Write-Host "Then rerun this script. Add Visual Studio 2022 Desktop development with C++ before building KDE Qt6 packages."
    exit 2
}

$settingsPath = Join-Path $CraftRoot "etc\CraftSettings.ini"
if (-not (Test-Path -LiteralPath $settingsPath)) {
    throw "CraftSettings.ini was not found at $settingsPath."
}

$settings = Get-Content -LiteralPath $settingsPath -Raw
if ($RepairSettings) {
    $settings = [regex]::Replace($settings, '(?m)^ABI\s*=\s*.*$', 'ABI = windows-cl-msvc2022-x86_64')
    $python312 = (& py -3.12 -c "import sys; print(sys.prefix)" 2>$null).Trim()
    if (-not $python312) { throw "Python 3.12 was not found through the py launcher." }
    $settings = [regex]::Replace($settings, '(?m)^Python\s*=\s*.*$', "Python = $python312")
    [System.IO.File]::WriteAllText($settingsPath, $settings, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Updated $settingsPath for PySide6/Qt MSVC compatibility." -ForegroundColor Green
}

$abiMatch = [regex]::Match($settings, '(?m)^ABI\s*=\s*(.+)$')
$abi = $abiMatch.Groups[1].Value.Trim()
if ($abi -ne "windows-cl-msvc2022-x86_64") {
    throw "Craft ABI is '$abi'. Run this script with -RepairSettings before installing the Qt/Kirigami runtime."
}

# Keep a standalone MinGW installation out of Craft's environment before the
# bootstrap script inspects PATH. PySide6 uses the MSVC Qt binaries here.
$env:PATH = (($env:PATH -split [IO.Path]::PathSeparator) | Where-Object {
    $_ -notmatch "mingw|x86_64-8\.1\.0-release"
}) -join [IO.Path]::PathSeparator

$previousErrorActionPreference = $ErrorActionPreference
# Some Craft releases try to remove an environment variable that is already
# gone. Keep that bootstrap warning non-fatal so the craft function is loaded.
$ErrorActionPreference = "Continue"
. $craftEnv
$ErrorActionPreference = $previousErrorActionPreference
$craftCommand = Get-Command craft -ErrorAction SilentlyContinue
if (-not $craftCommand) {
    throw "Craft command was not created after loading $craftEnv."
}

if ($InstallRuntime) {
    Write-Host "Installing Kirigami runtime through Craft..." -ForegroundColor Yellow
    craft craft/craft-blueprints-kde
    if ($LASTEXITCODE -ne 0) {
        throw "Craft failed while installing the KDE blueprint repository. This is often a transient MSYS2 mirror/network error; rerun the same command to resume from Craft's cache. Do not change the ABI."
    }
    craft kde/frameworks/tier1/kirigami kde/frameworks/tier3/qqc2-desktop-style kde/frameworks/tier1/breeze-icons
    if ($LASTEXITCODE -ne 0) {
        throw "Craft failed while installing the Kirigami runtime. This is often a transient KDE/MSYS2 mirror/network error; rerun the same command to resume from Craft's cache."
    }
}

$stableQmlRoot = Join-Path $CraftRoot "qml"
$stableQmlFile = Join-Path $stableQmlRoot "org\kde\kirigami\qmldir"
$qmlFiles = @()
if (Test-Path -LiteralPath $stableQmlFile) {
    $qmlFiles = @(Get-Item -LiteralPath $stableQmlFile)
} else {
    $qmlFiles = @(Get-ChildItem -LiteralPath $CraftRoot -Filter "qmldir" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "[\\/]org[\\/]kde[\\/]kirigami[\\/]qmldir$" })
}

if (-not $qmlFiles) {
    throw "Could not find org/kde/kirigami/qmldir below $CraftRoot. Run this script with -InstallRuntime or verify the Craft ABI/runtime."
}

# qmldir is below <import-root>/org/kde/kirigami; QML needs the directory
# containing `org`, not one of the module directories themselves.
$qmlImportPath = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $qmlFiles[0].FullName)))
$env:QML2_IMPORT_PATH = $qmlImportPath
$env:QML_IMPORT_PATH = $qmlImportPath
[Environment]::SetEnvironmentVariable("QML2_IMPORT_PATH", $qmlImportPath, "User")
[Environment]::SetEnvironmentVariable("QML_IMPORT_PATH", $qmlImportPath, "User")

Write-Host "Kirigami QML import path: $qmlImportPath" -ForegroundColor Green
Write-Host "User environment variables QML2_IMPORT_PATH and QML_IMPORT_PATH were updated."
Write-Host 'Verify with: uv run python -c "from shinar.desktop.app import kirigami_runtime_available; print(kirigami_runtime_available())"'

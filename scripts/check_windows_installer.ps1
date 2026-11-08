param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$BaselineInstaller
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'build/windows'))
$validationRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
if (-not $validationRoot.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Installer checks must use a new directory inside build/windows.'
}
if (Test-Path -LiteralPath $validationRoot) { throw 'Choose a new validation directory.' }
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$validationKey = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/Shinar.Desktop.Validation_is1'
$normalKey = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/Shinar.Desktop_is1'
if (Test-Path -LiteralPath $validationKey) { throw 'A prior validation install still needs its own uninstaller.' }
$normalPresent = Test-Path -LiteralPath $normalKey
$installRoot = Join-Path $validationRoot 'app'
New-Item -ItemType Directory -Path $validationRoot | Out-Null
$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/VALIDATE=1', '/TASKS=', ('/DIR="' + $installRoot + '"'), ('/LOG="' + (Join-Path $validationRoot 'install.log') + '"'))
$baselineBytes = 0
if ($BaselineInstaller) {
    $baselinePath = (Resolve-Path -LiteralPath $BaselineInstaller).Path
    $baselineArguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/VALIDATE=1', '/TASKS=', ('/DIR="' + $installRoot + '"'), ('/LOG="' + (Join-Path $validationRoot 'baseline.log') + '"'))
    $baseline = Start-Process -FilePath $baselinePath -ArgumentList $baselineArguments -WindowStyle Hidden -Wait -PassThru
    if ($baseline.ExitCode -ne 0) { throw ('Baseline installation failed: ' + $baseline.ExitCode) }
    $baselineBytes = (Get-ChildItem -LiteralPath $installRoot -Recurse -File | Measure-Object Length -Sum).Sum
}
$install = Start-Process -FilePath $installerPath -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($install.ExitCode -ne 0) { throw ('Installer failed: ' + $install.ExitCode) }
if (-not (Test-Path -LiteralPath $validationKey)) { throw 'Validation uninstall registration is missing.' }
$installedBytes = (Get-ChildItem -LiteralPath $installRoot -Recurse -File | Measure-Object Length -Sum).Sum
$retiredPresent = 0
$layoutFile = Join-Path $installRoot 'RUNTIME_LAYOUT.json'
if (Test-Path -LiteralPath $layoutFile) {
    $layout = Get-Content -LiteralPath $layoutFile -Raw | ConvertFrom-Json
    foreach ($entry in $layout.retired) {
        if (Test-Path -LiteralPath (Join-Path (Join-Path $installRoot 'runtime') $entry)) { $retiredPresent++ }
    }
    foreach ($entry in $layout.retained) {
        if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $installRoot 'runtime') $entry))) { throw 'A retained runtime file is missing.' }
    }
}

$keys = @('QT_QPA_PLATFORM', 'QT_QUICK_BACKEND', 'RUN_REAL_AI_TESTS', 'SHINAR_KIRIGAMI_MODE')
$previous = @{}
foreach ($key in $keys) { $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process') }
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:QT_QUICK_BACKEND = 'software'
    $env:RUN_REAL_AI_TESTS = '0'
    $env:SHINAR_KIRIGAMI_MODE = 'off'
    $launch = Start-Process -FilePath (Join-Path $installRoot 'Shinar.exe') -ArgumentList @('--mock', '--smoke') -WindowStyle Hidden -Wait -PassThru
    if ($launch.ExitCode -ne 0) { throw ('Installed launcher failed: ' + $launch.ExitCode) }
} finally {
    foreach ($key in $keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
}
$sentinelRoot = Join-Path $validationRoot 'user-data'
New-Item -ItemType Directory -Path $sentinelRoot | Out-Null
$sentinel = Join-Path $sentinelRoot 'keep.txt'
Set-Content -LiteralPath $sentinel -Value 'keep-user-data'
$uninstall = Start-Process -FilePath (Join-Path $installRoot 'unins000.exe') -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + (Join-Path $validationRoot 'uninstall.log') + '"')) -WindowStyle Hidden -Wait -PassThru
$remaining = @(Get-ChildItem -LiteralPath $installRoot -Recurse -File -ErrorAction SilentlyContinue).Count
$report = [ordered]@{
    installExit = $install.ExitCode
    installedLauncherExit = $launch.ExitCode
    uninstallExit = $uninstall.ExitCode
    validationRegistryRemoved = -not (Test-Path -LiteralPath $validationKey)
    normalInstallRegistrationUnchanged = (Test-Path -LiteralPath $normalKey) -eq $normalPresent
    externalUserDataRetained = (Get-Content -LiteralPath $sentinel -Raw).Trim() -eq 'keep-user-data'
    remainingProgramFiles = $remaining
    baselineInstalledBytes = $baselineBytes
    installedBytes = $installedBytes
    retiredFilesStillPresent = $retiredPresent
}
$json = $report | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $validationRoot 'report.json') -Value $json -Encoding utf8
Write-Output $json
if ($uninstall.ExitCode -ne 0 -or -not $report.validationRegistryRemoved -or -not $report.normalInstallRegistrationUnchanged -or -not $report.externalUserDataRetained -or $remaining -ne 0 -or $retiredPresent -ne 0 -or ($baselineBytes -gt 0 -and $installedBytes -ge $baselineBytes)) {
    throw 'Installer/uninstaller verification failed; see the validation report.'
}

param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolchain = Get-Content -LiteralPath (Join-Path $projectRoot 'packaging/windows/toolchain.json') -Raw | ConvertFrom-Json
$toolsRoot = Join-Path $projectRoot 'build/windows-tools'
$compilerRoot = Join-Path $toolsRoot ('inno-' + $toolchain.inno.version)
$compiler = Join-Path $compilerRoot 'ISCC.exe'
if (Test-Path -LiteralPath $compiler) {
    Write-Output $compiler
    exit 0
}
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
$installer = Join-Path $toolsRoot ('innosetup-' + $toolchain.inno.version + '.exe')
if (-not (Test-Path -LiteralPath $installer)) {
    Invoke-WebRequest -Uri $toolchain.inno.url -OutFile $installer
}
$digest = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
if ($digest -ne $toolchain.inno.sha256) {
    throw 'Inno Setup download failed SHA256 verification.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.GetNameInfo('SimpleName', $false) -ne $toolchain.inno.publisher) {
    throw 'Inno Setup publisher signature verification failed.'
}
# The official portable switch creates no uninstaller, Start menu entry or registry install.
$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/PORTABLE=1', '/CURRENTUSER', '/NOICONS', '/TASKS=', ('/DIR="' + $compilerRoot + '"'))
$process = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $compiler)) {
    throw ('Portable Inno Setup preparation failed: ' + $process.ExitCode)
}
Write-Output $compiler

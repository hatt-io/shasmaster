param([Parameter(Mandatory=$true)][ValidateSet('Release')][string]$Configuration, [switch]$Sign)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$root = (Get-Location).Path
$python = if ($env:SHAS_BUILD_PYTHON) { $env:SHAS_BUILD_PYTHON } else { Join-Path $root '.venv\Scripts\python.exe' }
$compiler = (Get-Command dotnet.exe -ErrorAction Stop).Source
$installer = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
foreach ($tool in @($python, $compiler, $installer)) { if (!(Test-Path $tool)) { throw "Build tool unavailable: $tool" } }
if (!(Test-Path 'data/prepared/manifest.json')) { throw 'Prepared content is required' }
$imported = $null
$scratch = Join-Path $root 'codex-tmp-native-windows'
if (Test-Path $scratch) { throw 'Previous Windows build staging exists; inspect it before another build' }
$oldTemp = $env:TEMP; $oldTmp = $env:TMP
New-Item -ItemType Directory $scratch | Out-Null
$env:TEMP = $scratch; $env:TMP = $scratch
try {
    if ($Sign -and !$env:SHAS_WINDOWS_THUMBPRINT) {
        if (!$env:SHAS_WINDOWS_CERTIFICATE -or !$env:SHAS_WINDOWS_CERTIFICATE_PASSWORD) { throw 'A Windows signing certificate and password are required' }
        $before = @(Get-ChildItem Cert:\CurrentUser\My | ForEach-Object { $_.Thumbprint })
        $password = ConvertTo-SecureString $env:SHAS_WINDOWS_CERTIFICATE_PASSWORD -AsPlainText -Force
        $certificate = Import-PfxCertificate -FilePath $env:SHAS_WINDOWS_CERTIFICATE -Password $password -CertStoreLocation Cert:\CurrentUser\My
        $env:SHAS_WINDOWS_THUMBPRINT = $certificate.Thumbprint
        if ($before -notcontains $certificate.Thumbprint) { $imported = $certificate.PSPath }
    }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Production frontend build failed' }
    & $python -m PyInstaller --noconfirm --distpath .desktop-build/runtime --workpath .desktop-build/python desktop/backend.spec
    if ($LASTEXITCODE -ne 0) { throw 'Release backend build failed' }
    New-Item -ItemType Directory -Force .desktop-build/windows-launcher,release | Out-Null
    & $compiler build native/WindowsApp.csproj --configuration Release --output "$root/.desktop-build/windows-launcher" "-p:BaseIntermediateOutputPath=$root/.desktop-build/windows-obj/"
    if ($LASTEXITCODE -ne 0) { throw 'Release launcher build failed' }
    $options = @("/DSourceRoot=$root")
    if ($Sign) {
        & "$PSScriptRoot/sign-windows.ps1" -Path '.desktop-build/windows-launcher/ShasMaster.exe'
        & "$PSScriptRoot/sign-windows.ps1" -Path '.desktop-build/runtime/shas-backend/shas-backend.exe'
        $signCommand = 'shasmaster=pwsh.exe -NoProfile -NonInteractive -File $q' + $PSScriptRoot + '\sign-windows.ps1$q -Path $f'
        $options += @('/DSignRelease', "/S$signCommand")
    }
    & $installer @options native/windows-installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed' }
    $suffix = if ($Sign) { '' } else { '-unsigned' }
    $installerBytes = (Get-Item "release/Shas-Master-Native-Windows-x64$suffix.exe").Length
    Write-Host "Windows installer: $installerBytes bytes"
    if ($installerBytes -gt 290000000) { throw "Installer is $installerBytes bytes, exceeding the 290 MB delivery limit" }
    if ($Sign) {
        $result = Get-AuthenticodeSignature 'release/Shas-Master-Native-Windows-x64.exe'
        if ($result.Status -ne 'Valid') { throw "Installer signature invalid: $($result.Status)" }
    } else { Write-Host 'Unsigned Release installer built; no signing certificate was used.' }
} finally {
    if ($imported) { Remove-Item $imported; Remove-Item Env:\SHAS_WINDOWS_THUMBPRINT }
    $env:TEMP = $oldTemp; $env:TMP = $oldTmp
    Remove-Item -Recurse $scratch
}

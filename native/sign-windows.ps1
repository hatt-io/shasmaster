param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
if (!$env:SHAS_WINDOWS_THUMBPRINT) { throw 'A Windows code-signing certificate must be selected' }
$certificate = Get-Item "Cert:\CurrentUser\My\$env:SHAS_WINDOWS_THUMBPRINT"
$result = Set-AuthenticodeSignature -FilePath $Path -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer 'http://timestamp.digicert.com'
if ($result.Status -ne 'Valid') { throw "Signing failed: $($result.StatusMessage)" }

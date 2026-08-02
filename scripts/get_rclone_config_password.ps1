$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security
$PasswordFile = Join-Path $env:LOCALAPPDATA "my-game-blog\phase4-backup\rclone-config-pass.dpapi"
if (-not (Test-Path -LiteralPath $PasswordFile -PathType Leaf)) { throw "The protected rclone configuration password was not found." }
$ProtectedBytes = [Convert]::FromBase64String([IO.File]::ReadAllText($PasswordFile, [Text.Encoding]::ASCII))
$PlainBytes = [Security.Cryptography.ProtectedData]::Unprotect(
    $ProtectedBytes,
    $null,
    [Security.Cryptography.DataProtectionScope]::CurrentUser
)
try {
    [Console]::Out.Write([Text.Encoding]::UTF8.GetString($PlainBytes))
} finally {
    if ($PlainBytes) { [Array]::Clear($PlainBytes, 0, $PlainBytes.Length) }
}

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security
$Rclone = Join-Path $env:LOCALAPPDATA "Programs\rclone\rclone.exe"
$PasswordReader = Join-Path $PSScriptRoot "get_rclone_config_password.ps1"
$StateRoot = Join-Path $env:LOCALAPPDATA "my-game-blog\phase4-backup"
$PasswordFile = Join-Path $StateRoot "rclone-config-pass.dpapi"
$ConfigFile = Join-Path $env:APPDATA "rclone\rclone.conf"

if (-not (Test-Path -LiteralPath $Rclone -PathType Leaf)) { throw "rclone.exe was not found." }
if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) { throw "The rclone configuration was not found." }
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null

function Convert-SecureToPlain([Security.SecureString]$Secure) {
    $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer) }
}

$First = Read-Host "New rclone configuration password" -AsSecureString
$Second = Read-Host "Enter the same password again" -AsSecureString
$FirstPlain = Convert-SecureToPlain $First
$SecondPlain = Convert-SecureToPlain $Second
try {
    if ([string]::IsNullOrWhiteSpace($FirstPlain) -or $FirstPlain.Length -lt 16) { throw "Use a configuration password of at least 16 characters." }
    if ($FirstPlain -cne $SecondPlain) { throw "The passwords do not match." }
    $PasswordBytes = [Text.Encoding]::UTF8.GetBytes($FirstPlain)
    try {
        $ProtectedBytes = [Security.Cryptography.ProtectedData]::Protect(
            $PasswordBytes,
            $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        [IO.File]::WriteAllText($PasswordFile, [Convert]::ToBase64String($ProtectedBytes), [Text.Encoding]::ASCII)
    } finally {
        if ($PasswordBytes) { [Array]::Clear($PasswordBytes, 0, $PasswordBytes.Length) }
    }
    $CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $null = & icacls.exe $PasswordFile /inheritance:r /grant:r "*$CurrentSid`:(F)" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Could not restrict access to the protected password file." }
    $PasswordCommand = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PasswordReader`""
    $null = & $Rclone config encryption set --password-command $PasswordCommand 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Could not encrypt the rclone configuration." }
    $null = & $Rclone config encryption check --password-command $PasswordCommand 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Could not verify the encrypted rclone configuration." }
    Write-Host "The rclone configuration is protected and was verified successfully." -ForegroundColor Green
} catch {
    if (-not ((Get-Content -LiteralPath $ConfigFile -TotalCount 1) -match 'Encrypted rclone configuration')) {
        Remove-Item -LiteralPath $PasswordFile -Force -ErrorAction SilentlyContinue
    }
    throw
} finally {
    $FirstPlain = $null
    $SecondPlain = $null
}

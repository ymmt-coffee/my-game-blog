$ErrorActionPreference = "Stop"

Write-Host "Paste your Steam Web API key and press Enter. The key will not be displayed."
$SecureKey = Read-Host -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
try {
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    if ($ApiKey -notmatch '^[0-9A-Fa-f]{32}$') {
        throw "The Steam Web API key must contain 32 hexadecimal characters."
    }
    $SteamId = (Read-Host "Enter your 17-digit Steam ID64").Trim()
    if ($SteamId -notmatch '^7656119[0-9]{10}$') {
        throw "The Steam ID64 format is invalid."
    }
    [Environment]::SetEnvironmentVariable("STEAM_WEB_API_KEY", $ApiKey.Trim(), "User")
    [Environment]::SetEnvironmentVariable("STEAM_ID64", $SteamId, "User")
}
finally {
    if ($Pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    }
    $ApiKey = $null
    $SecureKey = $null
}

Write-Host "Steam credentials saved. Restart the admin screen from the desktop icon."

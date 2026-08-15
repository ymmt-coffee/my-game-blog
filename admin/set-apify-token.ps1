$ErrorActionPreference = "Stop"

Write-Host "Paste your Apify API token and press Enter. The token will not be displayed."
$SecureToken = Read-Host -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
try {
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    if ([string]::IsNullOrWhiteSpace($Token)) {
        throw "The token is empty."
    }
    [Environment]::SetEnvironmentVariable("APIFY_API_TOKEN", $Token.Trim(), "User")
}
finally {
    if ($Pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    }
    $Token = $null
    $SecureToken = $null
}

Write-Host "Token saved. Close the admin screen and restart it from the desktop icon."

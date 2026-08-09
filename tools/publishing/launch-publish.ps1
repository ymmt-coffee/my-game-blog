param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceFile
)

$projectRoot = $PSScriptRoot
$publishScript = Join-Path $projectRoot "publish.ps1"
$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-NoExit",
    "-File", "`"$publishScript`"",
    "-SourceFile", "`"$SourceFile`"",
    "-Approve"
)

Start-Process powershell -ArgumentList $arguments -WindowStyle Normal

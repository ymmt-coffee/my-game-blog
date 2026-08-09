param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceFile
)

$projectRoot = $PSScriptRoot
$previewScript = Join-Path $projectRoot "preview.ps1"
$arguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$previewScript`"",
    "-SourceFile", "`"$SourceFile`""
)

Start-Process powershell -ArgumentList $arguments -WindowStyle Normal

param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceFile,

    [switch]$Interactive
)

$ErrorActionPreference = "Stop"

# Shell Commands runs its command in the background. Open a visible PowerShell
# window first so that the confirmation dialog and any error remain visible.
if (-not $Interactive) {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-NoExit",
        "-File", "`"$PSCommandPath`"",
        "-SourceFile", "`"$SourceFile`"",
        "-Interactive"
    )

    Start-Process powershell -ArgumentList $arguments -WindowStyle Normal
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
$messagesPath = Join-Path $PSScriptRoot "data\editorial\review-launcher-ja.json"
$messages = Get-Content -LiteralPath $messagesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$message = $messages.lines -join [Environment]::NewLine
$answer = [System.Windows.Forms.MessageBox]::Show(
    $message,
    $messages.title,
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
    exit 0
}

$projectRoot = $PSScriptRoot
$reviewScript = Join-Path $projectRoot "review.ps1"
& $reviewScript -SourceFile $SourceFile -Gemini -Replace

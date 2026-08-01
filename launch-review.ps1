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
$message = @"
Gemini 3.6 Flashで現在の記事を校正します。

- index.mdと画像は変更しません
- 修正案はreview-report.mdだけへ保存します
- 既存のreview-report.mdがある場合は置き換えます
- 記事本文はGeminiの無料枠へ送信されます

続行しますか？
"@
$answer = [System.Windows.Forms.MessageBox]::Show(
    $message,
    "ゲームブログ校正の確認",
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Question
)
if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
    exit 0
}

$projectRoot = $PSScriptRoot
$reviewScript = Join-Path $projectRoot "review.ps1"
& $reviewScript -SourceFile $SourceFile -Gemini -Replace

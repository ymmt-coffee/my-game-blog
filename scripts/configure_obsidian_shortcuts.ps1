param(
    [string]$VaultRoot = "C:\Users\ymmt_\Documents\Life_and_Div",
    [switch]$SkipProcessCheck
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$settingsDir = Join-Path $VaultRoot ".obsidian"
$shellConfigPath = Join-Path $settingsDir "plugins\obsidian-shellcommands\data.json"
$hotkeysPath = Join-Path $settingsDir "hotkeys.json"
$publishCommandId = "papo6svpi0"
$previewCommandId = "gameprev01"

if (-not $SkipProcessCheck) {
    $obsidianProcesses = @(Get-Process Obsidian -ErrorAction SilentlyContinue)
    if ($obsidianProcesses.Count -gt 0) {
        throw "Obsidian is running. Close Obsidian before updating shortcuts."
    }
}

if (-not (Test-Path -LiteralPath $shellConfigPath)) {
    throw "Shell Commands settings were not found: $shellConfigPath"
}
if (-not (Test-Path -LiteralPath $hotkeysPath)) {
    throw "Obsidian hotkeys were not found: $hotkeysPath"
}

$shellConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $shellConfigPath | ConvertFrom-Json
$hotkeys = Get-Content -Raw -Encoding UTF8 -LiteralPath $hotkeysPath | ConvertFrom-Json
$publishCommand = @($shellConfig.shell_commands | Where-Object { $_.id -eq $publishCommandId })
if ($publishCommand.Count -ne 1) {
    throw "Expected exactly one existing publish command with id $publishCommandId."
}

$previewLauncher = Join-Path $projectRoot "launch-preview.ps1"
$publishLauncher = Join-Path $projectRoot "launch-publish.ps1"
$publishCommandText = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$publishLauncher`" -SourceFile {{file_path:absolute}}"
$previewCommandText = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$previewLauncher`" -SourceFile {{file_path:absolute}}"

$publishCommand[0].alias = "Game blog: Publish current article"
$publishCommand[0].platform_specific_commands.default = $publishCommandText
$publishCommand[0].confirm_execution = $true
$publishCommand[0].icon = "lucide-upload"

$existingPreview = @($shellConfig.shell_commands | Where-Object { $_.id -eq $previewCommandId })
if ($existingPreview.Count -gt 1) {
    throw "Multiple preview commands use id $previewCommandId."
}
if ($existingPreview.Count -eq 0) {
    $previewCommand = ($publishCommand[0] | ConvertTo-Json -Depth 20 | ConvertFrom-Json)
    $previewCommand.id = $previewCommandId
    $shellConfig.shell_commands += $previewCommand
}
else {
    $previewCommand = $existingPreview[0]
}

$previewCommand.alias = "Game blog: Preview current article"
$previewCommand.platform_specific_commands.default = $previewCommandText
$previewCommand.confirm_execution = $false
$previewCommand.icon = "lucide-eye"

$publishHotkeyName = "obsidian-shellcommands:shell-command-$publishCommandId"
$previewHotkeyName = "obsidian-shellcommands:shell-command-$previewCommandId"
$publishHotkey = @([pscustomobject]@{ modifiers = @("Alt", "Shift"); key = "P" })
$previewHotkey = @([pscustomobject]@{ modifiers = @("Alt", "Shift"); key = "V" })
$hotkeys | Add-Member -NotePropertyName $publishHotkeyName -NotePropertyValue $publishHotkey -Force
$hotkeys | Add-Member -NotePropertyName $previewHotkeyName -NotePropertyValue $previewHotkey -Force

$backupRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("my-game-blog-obsidian-backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
Copy-Item -LiteralPath $shellConfigPath -Destination (Join-Path $backupRoot "data.json")
Copy-Item -LiteralPath $hotkeysPath -Destination (Join-Path $backupRoot "hotkeys.json")

$shellTemp = "$shellConfigPath.tmp"
$hotkeysTemp = "$hotkeysPath.tmp"
$shellConfig | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $shellTemp -Encoding UTF8
$hotkeys | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $hotkeysTemp -Encoding UTF8
Move-Item -LiteralPath $shellTemp -Destination $shellConfigPath -Force
Move-Item -LiteralPath $hotkeysTemp -Destination $hotkeysPath -Force

Write-Host "Obsidian shortcuts updated."
Write-Host "  Alt+Shift+V: Preview current game blog article"
Write-Host "  Alt+Shift+P: Publish current game blog article (confirmation required)"
Write-Host "  Backup: $backupRoot"

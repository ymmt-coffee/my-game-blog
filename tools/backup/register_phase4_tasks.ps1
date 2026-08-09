$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Runner = Join-Path $PSScriptRoot "run_phase4_backup.ps1"
$Remote = "gdrive-phase4-crypt:"
$DailyName = "my-game-blog Phase4 Daily Backup"
$MonthlyName = "my-game-blog Phase4 Monthly Snapshot"
$Created = @()

if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) { throw "The backup runner was not found." }

$Service = New-Object -ComObject "Schedule.Service"
$Service.Connect()
$Root = $Service.GetFolder("\")

function Test-TaskExists([string]$Name) {
    try { $null = $Root.GetTask("\$Name"); return $true }
    catch { return $false }
}

function New-Phase4Task([string]$Name, [string]$Mode) {
    if (Test-TaskExists $Name) { throw "A task with this name already exists; it will not be overwritten." }
    $Definition = $Service.NewTask(0)
    $Definition.RegistrationInfo.Description = "Phase 4 encrypted Google Drive backup. Registered disabled until full-backup approval."
    $Definition.Principal.UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $Definition.Principal.LogonType = 3
    $Definition.Principal.RunLevel = 0
    $Definition.Settings.Enabled = $false
    $Definition.Settings.StartWhenAvailable = $true
    $Definition.Settings.WakeToRun = $true
    $Definition.Settings.DisallowStartIfOnBatteries = $true
    $Definition.Settings.StopIfGoingOnBatteries = $false
    $Definition.Settings.MultipleInstances = 2
    $Definition.Settings.ExecutionTimeLimit = "PT2H"
    try {
        $Definition.Settings.RestartCount = 2
        $Definition.Settings.RestartInterval = "PT15M"
    } catch { throw "Could not configure task retry settings." }

    if ($Mode -eq "Daily") {
        $Trigger = $Definition.Triggers.Create(2)
        $Trigger.DaysInterval = 1
        $Trigger.StartBoundary = ((Get-Date).Date.AddDays(1).AddHours(2)).ToString("s")
    } else {
        $Trigger = $Definition.Triggers.Create(4)
        $Trigger.DaysOfMonth = 1
        $Trigger.MonthsOfYear = 4095
        $Trigger.StartBoundary = ((Get-Date).Date.AddDays(1).AddHours(3)).ToString("s")
    }
    $Trigger.Enabled = $true

    $Action = $Definition.Actions.Create(0)
    $Action.Path = "powershell.exe"
    $Action.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Runner`" -Mode $Mode -Remote `"$Remote`""
    $Action.WorkingDirectory = $ProjectRoot
    $null = $Root.RegisterTaskDefinition($Name, $Definition, 2, $null, $null, 3, $null)
    $script:Created += $Name
}

try {
    New-Phase4Task $DailyName "Daily"
    New-Phase4Task $MonthlyName "Monthly"
    [pscustomobject]@{
        RegisteredTasks = 2
        EnabledTasks = 0
        DailyTime = "02:00"
        MonthlyTime = "Day 1 03:00"
        LogonType = "InteractiveToken"
        FullBackupStarted = $false
    } | ConvertTo-Json -Compress
} catch {
    foreach ($Name in $Created) {
        try { $Root.DeleteTask($Name, 0) } catch {}
    }
    throw
}

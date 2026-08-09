param(
    [ValidateSet("Plan", "Daily", "Monthly")]
    [string]$Mode = "Plan",
    [string]$Remote = "",
    [switch]$DryRun,
    [switch]$Reconcile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ConfigPath = Join-Path $ProjectRoot "config\backup\phase4.json"
$FilterPath = Join-Path $ProjectRoot "config\backup\exclude-rules.txt"
$MonthlyFilterPath = Join-Path $ProjectRoot "config\backup\monthly-filter-rules.txt"
$StateRoot = Join-Path $env:LOCALAPPDATA "my-game-blog\phase4-backup"
$LockPath = Join-Path $StateRoot "backup.lock"
$RunId = [Guid]::NewGuid().ToString("N")
$RcloneExe = Join-Path $env:LOCALAPPDATA "Programs\rclone\rclone.exe"
$PasswordReader = Join-Path $PSScriptRoot "get_rclone_config_password.ps1"
$PasswordCommand = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PasswordReader`""

function Invoke-Rclone([string[]]$Arguments) {
    $PreviousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 can turn native stderr into a terminating
        # NativeCommandError even when the process exit code is zero.
        $ErrorActionPreference = "Continue"
        $script:RcloneOutput = @(& $RcloneExe @Arguments 2>$null)
        $script:RcloneExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $PreviousPreference
    }
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw "The Phase 4 configuration was not found." }
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$Source = [IO.Path]::GetFullPath([string]$Config.source)

if ($Mode -eq "Plan") {
    python (Join-Path $PSScriptRoot "phase4_backup.py") inventory --source $Source
    exit $LASTEXITCODE
}

if ([string]::IsNullOrWhiteSpace($Remote) -or $Remote -match "pending") {
    throw "An approved rclone remote and destination are required."
}
if (-not (Test-Path -LiteralPath $RcloneExe -PathType Leaf)) {
    throw "rclone is not installed."
}

New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
try {
    $Lock = [IO.File]::Open($LockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
} catch {
    throw "A backup is already running."
}

$FailureKind = "configuration"
try {
    $Destination = if ($Mode -eq "Monthly") {
        $FilterPath = $MonthlyFilterPath
        $Month = Get-Date -Format "yyyy-MM"
        "$Remote/monthly/$Month"
    } else {
        "$Remote/daily"
    }

    if ($Mode -eq "Monthly") {
        Invoke-Rclone @("lsf", "$Destination/.phase4-complete.json", "--password-command", $PasswordCommand)
        if (-not $Reconcile -and $RcloneExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace(($RcloneOutput -join ""))) {
            Write-Output '{"status":"already_complete","mode":"monthly"}'
            exit 0
        }
    }

    if ($Mode -eq "Monthly") {
        Invoke-Rclone @("size", $Source, "--filter-from", $FilterPath, "--skip-links", "--json", "--password-command", $PasswordCommand)
        if ($RcloneExitCode -ne 0) { throw "Could not inventory the monthly backup source." }
        try {
            $MonthlySize = ($RcloneOutput -join [Environment]::NewLine) | ConvertFrom-Json
            $Inventory = [pscustomobject]@{ files = [int64]$MonthlySize.count; bytes = [int64]$MonthlySize.bytes }
        } catch { throw "Could not safely parse the monthly backup inventory." }
    } else {
        $InventoryJson = python (Join-Path $PSScriptRoot "phase4_backup.py") inventory --source $Source
        if ($LASTEXITCODE -ne 0) { throw "Could not inventory the backup source." }
        $Inventory = $InventoryJson | ConvertFrom-Json
    }
    $FailureKind = "authentication"
    Invoke-Rclone @("about", $Remote, "--json", "--password-command", $PasswordCommand)
    $AboutJson = $RcloneOutput -join [Environment]::NewLine
    if ($RcloneExitCode -ne 0) { throw "Could not verify Google Drive capacity or authentication." }
    try { $About = $AboutJson | ConvertFrom-Json } catch { throw "Could not safely parse the Google Drive capacity response." }
    if ($null -eq $About.free -or $null -eq $About.total) { throw "Google Drive free capacity is unavailable." }
    $Reserve = [Math]::Max([int64]$Config.minimum_free_bytes, [int64]([int64]$About.total * [int]$Config.minimum_free_percent / 100))
    $FailureKind = "capacity"
    if ([int64]$About.free - [int64]$Inventory.bytes -lt $Reserve) { throw "Google Drive does not have enough safe free capacity." }

    $Args = @("copy", $Source, $Destination, "--filter-from", $FilterPath, "--skip-links", "--checkers", "8", "--transfers", "4", "--retries", "2", "--low-level-retries", "2", "--stats-one-line", "--log-level", "ERROR")
    if ($DryRun) { $Args += "--dry-run" }
    $FailureKind = "network"
    $Args += @("--password-command", $PasswordCommand)
    Invoke-Rclone $Args
    if ($RcloneExitCode -ne 0) { throw "rclone copy did not complete safely." }

    if (-not $DryRun) {
        $FailureKind = "verification"
        Invoke-Rclone @("check", $Source, $Destination, "--filter-from", $FilterPath, "--one-way", "--skip-links", "--password-command", $PasswordCommand)
        if ($RcloneExitCode -ne 0) { throw "Post-copy verification failed." }
        $Marker = Join-Path $StateRoot "$RunId-complete.json"
        @{ run_id = $RunId; files = [int64]$Inventory.files; bytes = [int64]$Inventory.bytes; mode = $Mode.ToLowerInvariant() } | ConvertTo-Json -Compress | Set-Content -LiteralPath $Marker -Encoding UTF8
        Invoke-Rclone @("copyto", $Marker, "$Destination/.phase4-complete.json", "--log-level", "ERROR", "--password-command", $PasswordCommand)
        Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
        if ($RcloneExitCode -ne 0) { throw "Could not save the verified completion marker." }
        @{ status = "success"; failure_kind = ""; run_id = $RunId; files = [int64]$Inventory.files; bytes = [int64]$Inventory.bytes; mode = $Mode.ToLowerInvariant() } | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $StateRoot "$RunId-status.json") -Encoding UTF8

        if ($Mode -eq "Monthly") {
            Invoke-Rclone @("lsf", "$Remote/monthly", "--dirs-only", "--password-command", $PasswordCommand)
            $MonthFolders = $RcloneOutput
            if ($RcloneExitCode -eq 0) {
                $Months = @($MonthFolders | ForEach-Object { $_.TrimEnd('/') } | Where-Object { $_ })
                $AllSafe = @($Months | Where-Object { $_ -notmatch '^20\d{2}-(0[1-9]|1[0-2])$' }).Count -eq 0
                if ($AllSafe -and $Months.Count -gt [int]$Config.monthly_snapshots_to_keep) {
                    $Candidates = @($Months | Sort-Object | Select-Object -First ($Months.Count - [int]$Config.monthly_snapshots_to_keep))
                    @{ status = "dry_run_only"; delete_enabled = $false; candidates = $Candidates } | ConvertTo-Json -Compress | Set-Content -LiteralPath (Join-Path $StateRoot "retention-dry-run.json") -Encoding UTF8
                }
            }
        }
    }
} catch {
    $OccurredAt = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"
    $StatePath = Join-Path $StateRoot "$RunId-status.json"
    @{ status = "failure"; failure_kind = $FailureKind; run_id = $RunId; occurred_at = $OccurredAt } | ConvertTo-Json -Compress | Set-Content -LiteralPath $StatePath -Encoding UTF8
    throw "The backup did not complete safely. Check the local non-secret status record."
} finally {
    if ($Lock) { $Lock.Dispose() }
    Remove-Item -LiteralPath $LockPath -Force -ErrorAction SilentlyContinue
}

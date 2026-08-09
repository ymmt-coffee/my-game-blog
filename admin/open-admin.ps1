$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AdminUrl = "http://127.0.0.1:8765/"
$HealthUrl = "http://127.0.0.1:8765/health"
$ExpectedVersion = (Get-Content -LiteralPath (Join-Path $PSScriptRoot "app-version.txt") -Raw).Trim()

function Get-AdminHealth {
    try {
        return Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 1
    }
    catch {
        return $null
    }
}

function Test-AdminReady {
    $Health = Get-AdminHealth
    return $null -ne $Health -and $Health.status -eq "ok" -and $Health.scope -eq "localhost_only"
}

function Stop-OutdatedAdmin {
    $Connection = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $Connection) {
        return
    }
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($Connection.OwningProcess)" -ErrorAction SilentlyContinue
    $IsAdmin = $null -ne $ProcessInfo -and `
        $ProcessInfo.Name -match '^python(w)?\.exe$' -and `
        $ProcessInfo.CommandLine -match '(^|\s)-m\s+admin\.run(\s|$)'
    if (-not $IsAdmin) {
        throw "ポート8765を別のアプリが使用しているため、安全のため自動再起動を停止しました。"
    }
    Stop-Process -Id $Connection.OwningProcess -Force -ErrorAction Stop
    for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
        Start-Sleep -Milliseconds 250
        if ($null -eq (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {
            return
        }
    }
    throw "古い管理画面を終了できませんでした。"
}

$Health = Get-AdminHealth
if ($null -ne $Health -and $Health.status -eq "ok" -and $Health.scope -eq "localhost_only" -and $Health.version -ne $ExpectedVersion) {
    Stop-OutdatedAdmin
    $Health = $null
}

if ($null -eq $Health -or $Health.status -ne "ok" -or $Health.scope -ne "localhost_only") {
    # このスクリプトを実行しているPowerShellと同じ版を使い、文字コードの差を避ける。
    $PowerShell = (Get-Process -Id $PID -ErrorAction Stop).Path
    $StartScript = Join-Path $PSScriptRoot "start-admin.ps1"
    Start-Process `
        -FilePath $PowerShell `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$StartScript`"") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden | Out-Null

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
        Start-Sleep -Milliseconds 250
        if (Test-AdminReady) {
            $Ready = $true
            break
        }
    }
    if (-not $Ready) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "管理画面を起動できませんでした。デスクトップアイコンをもう一度クリックしてください。",
            "ゲームブログ管理",
            "OK",
            "Error"
        ) | Out-Null
        exit 1
    }
}

Start-Process $AdminUrl

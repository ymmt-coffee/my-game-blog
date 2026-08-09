$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AdminUrl = "http://127.0.0.1:8765/"
$HealthUrl = "http://127.0.0.1:8765/health"

function Test-AdminReady {
    try {
        $Response = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 1
        return $Response.status -eq "ok" -and $Response.scope -eq "localhost_only"
    }
    catch {
        return $false
    }
}

if (-not (Test-AdminReady)) {
    # このスクリプトを実行しているPowerShellと同じ版を使い、文字コードの差を避ける。
    $PowerShell = (Get-Process -Id $PID -ErrorAction Stop).Path
    $StartScript = Join-Path $PSScriptRoot "start-admin.ps1"
    Start-Process `
        -FilePath $PowerShell `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$StartScript`"") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Minimized | Out-Null

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
            "管理画面を起動できませんでした。起動用ウィンドウのエラーを確認してください。",
            "ゲームブログ管理",
            "OK",
            "Error"
        ) | Out-Null
        exit 1
    }
}

Start-Process $AdminUrl

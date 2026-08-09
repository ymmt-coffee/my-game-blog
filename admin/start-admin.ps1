$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $ProjectRoot
$ErrorFile = Join-Path $ProjectRoot "var\admin\startup-error.txt"
try {
    python -m admin.run
    if ($LASTEXITCODE -ne 0) {
        throw "管理画面を起動できませんでした。"
    }
}
catch {
    $ErrorDirectory = Split-Path -Parent $ErrorFile
    New-Item -ItemType Directory -Path $ErrorDirectory -Force | Out-Null
    "管理画面の起動に失敗しました。デスクトップアイコンをもう一度クリックしてください。" | Set-Content -LiteralPath $ErrorFile -Encoding UTF8
    exit 1
}

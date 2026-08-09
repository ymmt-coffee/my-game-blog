$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $ProjectRoot
python -m admin.run
if ($LASTEXITCODE -ne 0) {
    throw "管理画面を起動できませんでした。"
}

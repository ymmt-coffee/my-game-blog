$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$ErrorActionPreference = "Stop"

function Write-StepResult {
    param(
        [string]$Step,
        [bool]$Success,
        [string]$Detail = ""
    )
    $status = if ($Success) { "OK" } else { "FAILED" }
    $color = if ($Success) { "Green" } else { "Red" }
    Write-Host "[$status] $Step" -ForegroundColor $color
    if ($Detail) { Write-Host "       $Detail" }
}

function Invoke-PublishStep {
    param(
        [string]$Number,
        [string]$Label,
        [scriptblock]$Action,
        [string]$SuccessDetail = ""
    )
    Write-Host ""
    Write-Host "[$Number] $Label"
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
        Write-StepResult -Step $Label -Success $true -Detail $SuccessDetail
    }
    catch {
        Write-StepResult -Step $Label -Success $false -Detail $_.Exception.Message
        exit 1
    }
}

Write-Host ""
Write-Host "=== publish.ps1 ===" -ForegroundColor Cyan
Write-Host ""

Invoke-PublishStep -Number "1/4" -Label "python scripts/sync_diary.py" -Action {
    python scripts/sync_diary.py
}

Invoke-PublishStep -Number "2/4" -Label "git add ." -Action {
    git add .
}

Write-Host ""
Write-Host "[3/4] git commit"
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    try {
        git commit -m "update posts"
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        Write-StepResult -Step "git commit" -Success $true -Detail "update posts"
    }
    catch {
        Write-StepResult -Step "git commit" -Success $false -Detail $_.Exception.Message
        exit 1
    }
}
else {
    Write-StepResult -Step "git commit" -Success $true -Detail "変更なし（スキップ）"
}

Invoke-PublishStep -Number "4/4" -Label "git push" -Action {
    git push
}

Write-Host ""
Write-Host "=== 完了 ===" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

Push-Location $projectRoot
try {
    git config --local core.hooksPath .githooks
    if ($LASTEXITCODE -ne 0) {
        throw "Could not configure the Git commit safety check."
    }
    $python = Get-Command python, py, python3 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $python) {
        throw "Python is required to verify the Git commit safety check."
    }
    if ($python.Name -eq "py.exe" -or $python.Name -eq "py") {
        & $python.Source -3 tools/security/check_staged_commit.py
    }
    else {
        & $python.Source tools/security/check_staged_commit.py
    }
    if ($LASTEXITCODE -ne 0) {
        throw "The Git commit safety check did not pass verification."
    }
    Write-Host "The Git commit safety check is enabled."
}
finally {
    Pop-Location
}

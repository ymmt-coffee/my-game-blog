param(
    [string]$Article = "",
    [string]$SourceFile = "",

    [switch]$Approve,
    [switch]$NoPush
)

$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BlogRoot = Join-Path $ProjectRoot "blog"
Set-Location $ProjectRoot
$ErrorActionPreference = "Stop"
$validationRoot = $null
$validationContent = $null
$validationSite = $null

function Invoke-CheckedCommand {
    param(
        [string]$Label,
        [scriptblock]$Action
    )
    Write-Host ""
    Write-Host "--- $Label ---" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed (exit code $LASTEXITCODE)"
    }
}

function Resolve-ArticleSlug {
    param(
        [string]$ExplicitArticle,
        [string]$ActiveSourceFile
    )

    if ($ExplicitArticle) {
        return $ExplicitArticle.Replace('\', '/').Trim('/')
    }
    if (-not $ActiveSourceFile) {
        throw "Article or SourceFile is required."
    }

    $sourceRoot = [System.IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Life_and_Div\30_Projects\01_blog"))
    $sourcePath = [System.IO.Path]::GetFullPath($ActiveSourceFile)
    $rootPrefix = $sourceRoot.TrimEnd('\') + '\'
    if (-not $sourcePath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The active file is outside the game blog source folder."
    }

    $relative = $sourcePath.Substring($rootPrefix.Length)
    $relativeParts = $relative -split '[\\/]'
    $fileName = $relativeParts[-1]
    $folderParts = @($relativeParts[0..([Math]::Max(0, $relativeParts.Count - 2))])

    if ($fileName -ieq "index.md" -or $fileName -ieq "review-report.md") {
        $slugParts = $folderParts
    }
    elseif ($relative -match '^(.*?)[\\/]images[\\/]') {
        $slugParts = @($Matches[1] -split '[\\/]')
    }
    elseif ([System.IO.Path]::GetExtension($fileName) -ieq ".md") {
        $relativeWithoutExtension = [System.IO.Path]::ChangeExtension($relative, $null)
        $slugParts = @($relativeWithoutExtension -split '[\\/]')
    }
    else {
        throw "Open index.md, review-report.md, or an article image before running this command."
    }

    $slug = ($slugParts | Where-Object { $_ }) -join '/'
    if (-not $slug) {
        throw "Could not determine the article slug from the active file."
    }
    return $slug
}

function Wait-ForPagesDeployment {
    param(
        [string]$CommitSha
    )

    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI is required to verify the Pages deployment."
    }

    $deadline = (Get-Date).AddMinutes(10)
    $runFound = $false
    while ((Get-Date) -lt $deadline) {
        $json = gh run list --repo ymmt-coffee/my-game-blog --workflow hugo.yml --event push --commit $CommitSha --limit 1 --json databaseId,status,conclusion,url
        if ($LASTEXITCODE -ne 0) {
            throw "Could not query the GitHub Actions run."
        }
        $runs = @($json | ConvertFrom-Json)
        if ($runs.Count -gt 0) {
            $runFound = $true
            $run = $runs[0]
            Write-Host "Actions: $($run.status) $($run.url)"
            if ($run.status -eq "completed") {
                if ($run.conclusion -ne "success") {
                    throw "GitHub Pages deployment failed: $($run.url)"
                }

                $response = Invoke-WebRequest -Uri "https://framing-games.com/" -UseBasicParsing -TimeoutSec 30
                if ([int]$response.StatusCode -ne 200) {
                    throw "Pages returned HTTP $($response.StatusCode)."
                }
                Write-Host "Pages deployment succeeded and the public URL returned HTTP 200." -ForegroundColor Green
                return
            }
        }
        Start-Sleep -Seconds 5
    }

    if ($runFound) {
        throw "Timed out while waiting for the Pages deployment."
    }
    throw "No GitHub Actions run appeared for commit $CommitSha."
}

try {
    $Article = Resolve-ArticleSlug -ExplicitArticle $Article -ActiveSourceFile $SourceFile
    Write-Host ""
    Write-Host "=== game blog publish ===" -ForegroundColor Cyan
    Write-Host "Article: $Article"

    if (-not $Approve) {
        throw "Approval is required. Run this from the publish shortcut after preview."
    }

    Invoke-CheckedCommand "Check proofreading report safety and freshness" {
        python (Join-Path $PSScriptRoot "review_article.py") --article $Article --status
    }

    if ($Article -match '(^|[\\/])\.\.([\\/]|$)' -or [System.IO.Path]::IsPathRooted($Article)) {
        throw "Invalid article slug: $Article"
    }

    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Staged changes already exist. Publishing stopped to avoid mixing changes."
    }

    $articlePath = "blog/content/posts/$($Article.Replace('\', '/').Trim('/'))"
    $managedChanges = @(git status --porcelain -- $articlePath)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the article Git status."
    }
    if ($managedChanges.Count -gt 0) {
        throw "The generated article has uncommitted changes. Publishing stopped: $articlePath"
    }

    $validationRoot = Join-Path ([System.IO.Path]::GetTempPath()) "my-game-blog-validation-$PID"
    $validationContent = Join-Path $validationRoot "content"
    $validationSite = Join-Path $validationRoot "public"
    New-Item -ItemType Directory -Path $validationRoot -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $BlogRoot "content") -Destination $validationContent -Recurse

    Invoke-CheckedCommand "Sync approved article to the validation area" {
        python (Join-Path $PSScriptRoot "sync_diary.py") --article $Article --require-publishable --output (Join-Path $validationContent "posts")
    }

    Invoke-CheckedCommand "Validate publishable content" {
        python (Join-Path $PSScriptRoot "validate_blog.py") --content-dir $validationContent --article $Article --production
    }

    Invoke-CheckedCommand "Pre-publish Hugo build" {
        hugo --source $BlogRoot --minify --environment production --contentDir $validationContent --destination $validationSite --cleanDestinationDir
    }

    Invoke-CheckedCommand "Validate generated site" {
        python (Join-Path $PSScriptRoot "validate_blog.py") --content-dir $validationContent --article $Article --production --public-dir $validationSite
    }

    Invoke-CheckedCommand "Sync approved article as a Page Bundle" {
        python (Join-Path $PSScriptRoot "sync_diary.py") --article $Article --require-publishable
    }

    Invoke-CheckedCommand "Stage only the selected article" {
        git add -- $articlePath
    }

    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "No article changes. Commit and push were skipped." -ForegroundColor Yellow
        exit 0
    }

    $stagedOutsideArticle = @(git diff --cached --name-only | Where-Object {
        $_ -ne $articlePath -and -not $_.StartsWith("$articlePath/")
    })
    if ($stagedOutsideArticle.Count -gt 0) {
        git restore --staged -- $articlePath
        throw "A path outside the selected article was staged. Publishing stopped."
    }

    Invoke-CheckedCommand "Commit the selected article" {
        git commit -m "publish: $Article" -- $articlePath
    }

    if ($NoPush) {
        Write-Host ""
        Write-Host "NoPush was specified. Push was skipped." -ForegroundColor Yellow
        exit 0
    }

    Invoke-CheckedCommand "Push to GitHub" {
        git push
    }

    Write-Host ""
    $publishedCommit = (git rev-parse HEAD).Trim()
    Write-Host "Waiting for the GitHub Pages deployment..." -ForegroundColor Cyan
    Wait-ForPagesDeployment -CommitSha $publishedCommit
}
catch {
    Write-Host ""
    Write-Host "[PUBLISH STOPPED] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if ($validationRoot) {
        $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
        $resolvedValidation = [System.IO.Path]::GetFullPath($validationRoot)
        if ($resolvedValidation.StartsWith($resolvedTemp) -and (Split-Path $resolvedValidation -Leaf).StartsWith("my-game-blog-validation-")) {
            Remove-Item -LiteralPath $resolvedValidation -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

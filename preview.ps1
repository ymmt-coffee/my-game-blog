param(
    [string]$Article = "",
    [string]$SourceFile = ""
)

$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

$previewRoot = Join-Path ([System.IO.Path]::GetTempPath()) "my-game-blog-preview-$PID"
$previewContent = Join-Path $previewRoot "content"
$previewPosts = Join-Path $previewContent "posts"

function Resolve-ArticleSlug {
    param(
        [string]$ExplicitArticle,
        [string]$ActiveSourceFile
    )

    if ($ExplicitArticle) {
        return $ExplicitArticle.Replace('\', '/').Trim('/')
    }
    if (-not $ActiveSourceFile) {
        return ""
    }

    $sourceRoot = [System.IO.Path]::GetFullPath("C:\Users\ymmt_\Documents\Life_and_Div\30_Projects\01_blog")
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

    return (($slugParts | Where-Object { $_ }) -join '/')
}

try {
    $Article = Resolve-ArticleSlug -ExplicitArticle $Article -ActiveSourceFile $SourceFile
    New-Item -ItemType Directory -Path $previewPosts -Force | Out-Null

    $syncArgs = @("scripts/sync_diary.py", "--output", $previewPosts)
    if ($Article) {
        $syncArgs += @("--article", $Article)
    }

    Write-Host ""
    Write-Host "=== game blog preview ===" -ForegroundColor Cyan
    python @syncArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Preview sync failed."
    }

    Write-Host ""
    Write-Host "Open http://localhost:1313/my-game-blog/ in your browser." -ForegroundColor Green
    Write-Host "Press Ctrl+C in this window to stop the preview."
    hugo server --buildDrafts --contentDir $previewContent --disableFastRender
    if ($LASTEXITCODE -ne 0) {
        throw "Hugo preview failed to start."
    }
}
catch {
    Write-Host ""
    Write-Host "[PREVIEW STOPPED] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $resolvedPreview = [System.IO.Path]::GetFullPath($previewRoot)
    if ($resolvedPreview.StartsWith($resolvedTemp) -and (Split-Path $resolvedPreview -Leaf).StartsWith("my-game-blog-preview-")) {
        Remove-Item -LiteralPath $resolvedPreview -Recurse -Force -ErrorAction SilentlyContinue
    }
}

param(
    [string]$Article = "",
    [string]$SourceFile = "",
    [switch]$DryRun,
    [switch]$PrintRequest,
    [switch]$Fake,
    [switch]$Gemini,
    [switch]$Status,
    [string]$ResponseFile = "",
    [string]$Method = "manual structured response",
    [switch]$Replace
)

$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot
$ErrorActionPreference = "Stop"

function Resolve-ArticleSlug {
    param([string]$ExplicitArticle, [string]$ActiveSourceFile)
    if ($ExplicitArticle) { return $ExplicitArticle.Replace('\', '/').Trim('/') }
    if (-not $ActiveSourceFile) { throw "Article or SourceFile is required." }
    $sourceRoot = [System.IO.Path]::GetFullPath("C:\Users\ymmt_\Documents\Life_and_Div\30_Projects\01_blog")
    $sourcePath = [System.IO.Path]::GetFullPath($ActiveSourceFile)
    $rootPrefix = $sourceRoot.TrimEnd('\') + '\'
    if (-not $sourcePath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The active file is outside the game blog source folder."
    }
    $relative = $sourcePath.Substring($rootPrefix.Length)
    if ($relative -match '^(.*?)[\\/](?:index\.md|review-report\.md)$' -or $relative -match '^(.*?)[\\/]images[\\/]') {
        return $Matches[1].Replace('\', '/')
    }
    throw "Open index.md, review-report.md, or an article image before running this command."
}

try {
    $Article = Resolve-ArticleSlug -ExplicitArticle $Article -ActiveSourceFile $SourceFile
    $argsList = @((Join-Path $PSScriptRoot "review_article.py"), "--article", $Article)
    if ($DryRun) { $argsList += "--dry-run" }
    elseif ($PrintRequest) { $argsList += "--print-request" }
    elseif ($Fake) { $argsList += "--fake" }
    elseif ($Gemini) { $argsList += "--gemini" }
    elseif ($Status) { $argsList += "--status" }
    elseif ($ResponseFile) { $argsList += @("--response-file", $ResponseFile, "--method", $Method) }
    else { throw "Choose DryRun, PrintRequest, Fake, Gemini, Status, or ResponseFile." }
    if ($Replace) { $argsList += "--replace" }
    python @argsList
    if ($LASTEXITCODE -ne 0) { throw "Review operation stopped safely." }
}
catch {
    Write-Host ""
    Write-Host "[REVIEW STOPPED] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Guided GitHub publisher for MedIntel — run this once to publish under YOUR name.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\publish_github.ps1
#
# What it does:
#   1. Asks for your name / email / GitHub username
#   2. Stamps your identity on ALL commits (including the initial ones)
#   3. Opens your browser on GitHub's "New repository" page and waits
#   4. Connects the remote and pushes
#
# You only interact with: 4 short prompts + one GitHub page + one sign-in popup.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Read-Value($prompt, $default) {
    if ($default) {
        $v = Read-Host "$prompt [$default]"
        if ([string]::IsNullOrWhiteSpace($v)) { return $default }
    } else {
        $v = Read-Host $prompt
        while ([string]::IsNullOrWhiteSpace($v)) { $v = Read-Host $prompt }
    }
    return $v.Trim()
}

Write-Host ""
Write-Host "=== MedIntel -> GitHub publisher ===" -ForegroundColor Cyan
Write-Host ""

# ---- 1. Collect your identity ----------------------------------------------
$name  = Read-Value "1/4  Your full name (shown on commits, e.g. 'Ananya Rao')"
$email = Read-Value "2/4  Email for commits"
Write-Host "     TIP: for privacy you can use GitHub's no-reply form:" -ForegroundColor DarkGray
Write-Host "          <username>@users.noreply.github.com" -ForegroundColor DarkGray
$user  = Read-Value "3/4  Your GitHub username (from github.com/<this>)"
$repo  = Read-Value "4/4  Repository name" "medical-document-intelligence"

# ---- 2. Stamp identity on every commit --------------------------------------
git config user.name  $name
git config user.email $email
Write-Host ""
Write-Host "Rewriting all 4 commits with your identity..." -ForegroundColor Yellow
git rebase -r --root --exec "git commit --amend --no-edit --reset-author" | Out-Null
Write-Host "Done. Latest commits:" -ForegroundColor Green
git log --format="  %h  %an  %s" -3

# ---- 3. Create the repo on GitHub (browser) ---------------------------------
Write-Host ""
Write-Host "NOW DO THIS IN THE BROWSER TAB THAT OPENS:" -ForegroundColor Cyan
Write-Host "  a. Sign in to github.com (email + password)."
Write-Host "  b. Repository name : $repo"
Write-Host "  c. Description     : AI medical document intelligence platform - grounded RAG with verifiable citations, OCR, comparison and contradiction detection (FastAPI + Next.js)"
Write-Host "  d. Select          : Public"
Write-Host "  e. DO NOT tick     : 'Add a README' / '.gitignore' / 'license'  (project already has them)"
Write-Host "  f. Click the green 'Create repository' button."
Write-Host ""
Start-Process "https://github.com/new"
Read-Host "Press ENTER once the green 'Create repository' page shows the next screen"

# ---- 4. Connect + push -------------------------------------------------------
$remote = "https://github.com/$user/$repo.git"
Write-Host ""
Write-Host "Pushing to $remote ..." -ForegroundColor Yellow
git remote remove origin 2>$null
git remote add origin $remote

$pushed = $false
try {
    git push -u origin master
    if ($LASTEXITCODE -eq 0) { $pushed = $true }
} catch { }

if (-not $pushed) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Push was rejected. Most common cause: the GitHub repo was created" -ForegroundColor Red
        Write-Host "WITH a README/license ticked. Two fixes:" -ForegroundColor Red
        Write-Host "  A) On GitHub: repo page -> Settings (bottom) -> Delete this repository," -ForegroundColor Red
        Write-Host "     then create it again with NO ticks, then run this script again" -ForegroundColor Red
        Write-Host "     (it is safe to re-run)." -ForegroundColor Red
        Write-Host "  B) Or run:  git pull origin master --allow-unrelated-histories" -ForegroundColor Red
        Write-Host "     then:     git push -u origin master" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "=== PUBLISHED ===" -ForegroundColor Green
Write-Host "Your project: https://github.com/$user/$repo" -ForegroundColor Green
Write-Host ""
Write-Host "Verify in the browser:" -ForegroundColor Cyan
Write-Host "  - Files list shows backend/ frontend/ evals/ docs/ README.md"
Write-Host "  - README is rendered with the architecture diagram"
Write-Host "  - Commits tab shows YOUR name on all commits"

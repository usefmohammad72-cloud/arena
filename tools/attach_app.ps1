#Requires -Version 5.1
<#
    attach_app.ps1 - package the STM application sources from a local Windows folder
                     and optionally push them to the arena GitHub repository.

    Usage (normal - just build a ZIP you can upload to the chat):
        powershell -ExecutionPolicy Bypass -File .\attach_app.ps1

    Usage (custom source path):
        powershell -ExecutionPolicy Bypass -File .\attach_app.ps1 -Source "D:\moghatee\samane\app"

    Usage (also push the sources to GitHub so the agent can read them):
        powershell -ExecutionPolicy Bypass -File .\attach_app.ps1 -Push

    Nothing sensitive is copied: venv, data (app.db / uploads), logs, backups,
    __pycache__, build outputs and *.key files are excluded on purpose.
#>

[CmdletBinding()]
param(
    [string] $Source    = 'D:\moghatee\samane\app',
    [string] $ZipPath   = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'stm-code.zip'),
    [switch] $Push,
    [string] $RemoteUrl = 'https://github.com/usefmohammad72-cloud/arena.git',
    [string] $Branch    = 'arena/2c734307-arena'
)

$ErrorActionPreference = 'Stop'

# Directory / file names that must never leave the local machine.
$ExcludeDirs  = @('venv', '__pycache__', 'data', 'logs', 'backups', 'build', 'dist',
                  'dist_installer', 'node_modules', '.git', '.idea', '.vscode',
                  '.pytest_cache', '.mypy_cache')
$ExcludeFiles = @('*.pyc', '*.pyo', '*.db', '*.db-journal', '*.exe', '*.zip', '*.7z',
                  '*.rar', '*.key', '*.log', '*.bak', '*.bak_*', '*.tmp')

# Repository files that must not be overwritten by the local copy.
$KeepRepoFiles = @('README.md', '.gitignore', 'REVIEW.md')

function Write-Step([string] $text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Write-Ok([string] $text)   { Write-Host "   [ok] $text" -ForegroundColor Green }
function Write-Warn2([string] $text){ Write-Host "   [!!] $text" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 1. validate
Write-Step "Checking source folder"
if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
    Write-Host "   [x] Source not found: $Source" -ForegroundColor Red
    Write-Host "       Pass the real path with -Source `"<path>`""
    exit 1
}
$Source = (Resolve-Path -LiteralPath $Source).Path
Write-Ok "source = $Source"

$expected = @('web\app.py', 'engine', 'importer', 'db')
$missing  = @()
foreach ($item in $expected) {
    if (Test-Path -LiteralPath (Join-Path $Source $item)) { Write-Ok $item }
    else { Write-Warn2 "missing: $item"; $missing += $item }
}
if ($missing.Count -gt 0) {
    Write-Warn2 "Some expected parts were not found. Packaging whatever exists."
}

# ---------------------------------------------------------------- 2. stage
Write-Step "Copying sources (excluding secrets and junk)"
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ('stm_stage_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $stage -Force | Out-Null

$robocopyArgs = @($Source, $stage, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
if ($ExcludeDirs.Count  -gt 0) { $robocopyArgs += '/XD'; $robocopyArgs += $ExcludeDirs }
if ($ExcludeFiles.Count -gt 0) { $robocopyArgs += '/XF'; $robocopyArgs += $ExcludeFiles }

& robocopy @robocopyArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) {
    Write-Host "   [x] robocopy failed with code $rc" -ForegroundColor Red
    exit 1
}
Write-Ok "robocopy exit code $rc (0-7 = success)"

$files = Get-ChildItem -LiteralPath $stage -Recurse -File
$totalMb = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 2)
Write-Ok ("{0} files, {1} MB" -f $files.Count, $totalMb)

# A short manifest so the reviewer can see what is inside without unzipping.
$manifest = Join-Path $stage 'MANIFEST.txt'
$lines = @()
$lines += "STM source snapshot"
$lines += "created : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$lines += "source  : $Source"
$lines += "files   : $($files.Count)  size: $totalMb MB"
$lines += ""
$lines += "--- excluded on purpose ---"
$lines += "dirs : $($ExcludeDirs -join ', ')"
$lines += "files: $($ExcludeFiles -join ', ')"
$lines += ""
$lines += "--- content ---"
$lines += ($files | ForEach-Object { $_.FullName.Substring($stage.Length + 1) } | Sort-Object)
Set-Content -LiteralPath $manifest -Value $lines -Encoding UTF8

# ---------------------------------------------------------------- 3. zip
Write-Step "Building ZIP"
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Ok ("{0} ({1} MB)" -f $ZipPath, [math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 2))
Write-Host ""
Write-Host "   Next step (option A): attach this ZIP in the Arena chat." -ForegroundColor White
Write-Host "   Next step (option B): re-run this script with -Push to upload it to GitHub." -ForegroundColor White

# ---------------------------------------------------------------- 4. optional push
if ($Push) {
    Write-Step "Pushing sources to GitHub"
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Host "   [x] git is not installed. Install from https://git-scm.com and retry." -ForegroundColor Red
        exit 1
    }

    $repo = Join-Path ([System.IO.Path]::GetTempPath()) ('arena_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    & git clone --branch $Branch --single-branch $RemoteUrl $repo
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [x] git clone failed. Check your GitHub access and retry." -ForegroundColor Red
        exit 1
    }
    Write-Ok "cloned $Branch"

    $copyArgs = @($stage, $repo, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
    $copyArgs += '/XF'; $copyArgs += $KeepRepoFiles
    & robocopy @copyArgs | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Host "   [x] copy into the repository failed" -ForegroundColor Red
        exit 1
    }

    Push-Location $repo
    try {
        & git add -A
        & git -c user.name="STM uploader" -c user.email="noreply@example.com" `
              commit -m ("sources: import STM application code from local machine ({0})" -f (Get-Date -Format 'yyyy-MM-dd'))
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 "Nothing new to commit (sources already up to date)."
        } else {
            & git push origin $Branch
            if ($LASTEXITCODE -ne 0) {
                Write-Host "   [x] push failed. Sign in to GitHub when prompted and retry." -ForegroundColor Red
                exit 1
            }
            Write-Ok "pushed to $Branch"
            Write-Host ("   {0}/tree/{1}" -f $RemoteUrl.TrimEnd('.git'), $Branch) -ForegroundColor White
        }
    }
    finally {
        Pop-Location
        Remove-Item -LiteralPath $repo -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
Write-Step "Done"

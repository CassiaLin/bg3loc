[CmdletBinding()]
param(
    [string]$GameDir = 'C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3',
    [string]$SourceLocale = 'English',
    [string]$TargetLocale = 'ChineseTraditional',
    [string]$Workspace = 'workspace',
    [string]$ReturnedInput = '',
    [string]$DivineExe = '',
    [string]$DivineDll = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-BG3Loc {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    Write-Host ("> bg3loc " + ($Arguments -join ' '))
    & bg3loc @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "bg3loc failed with exit code $LASTEXITCODE"
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Require-File {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file not found: $Path"
    }
}

if ($DivineExe) {
    Require-File $DivineExe
    $env:BG3LOC_DIVINE_EXE = (Resolve-Path -LiteralPath $DivineExe).Path
}
if ($DivineDll) {
    Require-File $DivineDll
    $env:BG3LOC_DIVINE_DLL = (Resolve-Path -LiteralPath $DivineDll).Path
}

if (-not (Get-Command bg3loc -ErrorAction SilentlyContinue)) {
    throw 'bg3loc is not available on PATH. Activate the project virtual environment and install with: python -m pip install -e .'
}
if (-not (Test-Path -LiteralPath $GameDir -PathType Container)) {
    throw "BG3 game directory not found: $GameDir"
}

$Workspace = [System.IO.Path]::GetFullPath($Workspace)
$ScanManifest = Join-Path $Workspace 'scan-manifest.json'
$ExtractDir = Join-Path $Workspace 'extract'
$BuildDir = Join-Path $Workspace 'build'
$ValidateDir = Join-Path $Workspace 'validate'
$RebuildDir = Join-Path $Workspace 'rebuild'
$BackupDir = Join-Path $Workspace 'backups'

Write-Host '=== Windows Tier 1 Acceptance / Windows Tier 1 實機驗收 ==='
Write-Host "GameDir: $GameDir"
Write-Host "Source:  $SourceLocale"
Write-Host "Target:  $TargetLocale"
Write-Host "Workspace: $Workspace"

Invoke-BG3Loc scan '--game-dir' $GameDir '--output' $ScanManifest
Require-File $ScanManifest

$Scan = Get-Content -LiteralPath $ScanManifest -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Scan.game.id -ne 'bg3' -or [string]$Scan.game.appId -ne '1086940') {
    throw 'scan-manifest game identity is not BG3 / app 1086940'
}

$TargetMatches = @($Scan.locales | Where-Object { $_.localeId -ieq $TargetLocale })
if ($TargetMatches.Count -ne 1) {
    throw "Expected exactly one target locale in scan manifest; found $($TargetMatches.Count)"
}
$TargetPackage = [string]$TargetMatches[0].packageFile
Require-File $TargetPackage
$BeforeSha = Get-Sha256 $TargetPackage
if ($BeforeSha -ne ([string]$TargetMatches[0].packageSha256).ToLowerInvariant()) {
    throw 'Current target package hash does not match scan manifest immediately after scan'
}

Invoke-BG3Loc extract '--scan' $ScanManifest '--source' $SourceLocale '--target' $TargetLocale '--output' $ExtractDir
$ExtractManifest = Join-Path $ExtractDir 'extract-manifest.json'
Require-File $ExtractManifest

Invoke-BG3Loc build '--extract' $ExtractManifest '--mode' 'basic' '--format' 'csv' '--max-rows' '1500' '--output' $BuildDir
$BuildManifest = Join-Path $BuildDir 'build-manifest.json'
Require-File $BuildManifest

$AfterBuildSha = Get-Sha256 $TargetPackage
if ($AfterBuildSha -ne $BeforeSha) {
    throw 'SAFETY FAILURE: target package changed during scan/extract/build'
}

Write-Host ''
Write-Host 'PASS: scan -> extract -> build completed without modifying the target game package.'
Write-Host "Target package SHA-256: $BeforeSha"

if (-not $ReturnedInput) {
    Write-Host ''
    Write-Host 'STOPPED AT SAFE HANDOFF.'
    Write-Host 'Create/edit a controlled returned CSV under workspace\returns, then re-run with:'
    Write-Host '  -ReturnedInput "workspace\returns\*.csv"'
    exit 0
}

Invoke-BG3Loc validate '--build' $BuildManifest '--input' $ReturnedInput '--output' $ValidateDir
$ValidateManifest = Join-Path $ValidateDir 'validate-manifest.json'
Require-File $ValidateManifest

Invoke-BG3Loc rebuild '--validate' $ValidateManifest '--extract' $ExtractManifest '--container' 'auto' '--output' $RebuildDir
$RebuildManifest = Join-Path $RebuildDir 'rebuild-manifest.json'
Require-File $RebuildManifest

$BeforeDryRunSha = Get-Sha256 $TargetPackage
Invoke-BG3Loc install '--rebuild' $RebuildManifest '--scan' $ScanManifest '--game-dir' $GameDir '--backup-dir' $BackupDir '--dry-run'
$AfterDryRunSha = Get-Sha256 $TargetPackage

if ($AfterDryRunSha -ne $BeforeDryRunSha) {
    throw 'SAFETY FAILURE: target package changed during install --dry-run'
}
if (Test-Path -LiteralPath $BackupDir) {
    $BackupFiles = @(Get-ChildItem -LiteralPath $BackupDir -Recurse -File -ErrorAction SilentlyContinue)
    if ($BackupFiles.Count -gt 0) {
        throw 'SAFETY FAILURE: install --dry-run created backup files'
    }
}

Write-Host ''
Write-Host 'PASS: Windows Tier 1 dry-run acceptance completed.'
Write-Host "Target package SHA-256 unchanged: $AfterDryRunSha"
Write-Host 'No game write has been approved or performed by this harness.'

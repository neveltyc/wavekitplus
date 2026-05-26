[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$CommitMessage = '',
    [string]$TagMessage = '',

    [switch]$DryRun,
    [switch]$SkipPytest,
    [switch]$RequirePytest,
    [switch]$SkipVersionCheck,
    [switch]$AllowNoCommit,
    [switch]$KeepGeneratedFixtureDates,
    [switch]$NoStageAll
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-GitOutput {
    param([string[]]$Arguments)

    $output = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return ($output -join "`n").Trim()
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host ">> $FilePath $($Arguments -join ' ')"
    if ($DryRun) {
        return
    }

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Copy-IfExists {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (Test-Path -LiteralPath $Source) {
        $parent = Split-Path -Parent $Destination
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
    }
}

function Restore-IfExists {
    param(
        [string]$Backup,
        [string]$Destination
    )

    if (Test-Path -LiteralPath $Backup) {
        Copy-Item -LiteralPath $Backup -Destination $Destination -Force
    }
}

function Clear-DateOnlyFixtureDiff {
    param([string]$Path)

    $diff = & git diff --unified=0 -- $Path
    if ($LASTEXITCODE -ne 0) {
        throw "git diff -- $Path failed with exit code $LASTEXITCODE"
    }

    $changedLines = @(
        $diff | Where-Object {
            $_ -match '^[+-]' -and $_ -notmatch '^(---|\+\+\+)'
        }
    )
    if ($changedLines.Count -eq 0) {
        return
    }

    $nonDateLines = @(
        $changedLines | Where-Object {
            $_ -notmatch '^[+-]\s+[A-Za-z]{3}\s+[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\d{4}\s*$'
        }
    )

    if ($nonDateLines.Count -eq 0) {
        Write-Host "Restoring timestamp-only generated fixture diff: $Path"
        Invoke-External git @('restore', '--worktree', '--', $Path)
    }
    else {
        Write-Warning "Generated fixture has non-date changes and will be left untouched: $Path"
    }
}

$tagName = if ($Version.StartsWith('v')) { $Version } else { "v$Version" }
$plainVersion = $tagName.Substring(1)

if ($tagName -notmatch '^v\d+\.\d+\.\d+([-.][0-9A-Za-z.]+)?$') {
    throw "Version must look like v1.2.3 or 1.2.3, got '$Version'"
}

$repoRoot = Get-GitOutput @('rev-parse', '--show-toplevel')
Set-Location $repoRoot

Write-Host "Release tag: $tagName"
Write-Host "Repository : $repoRoot"

$branch = Get-GitOutput @('branch', '--show-current')
if (-not $branch) {
    throw 'Refusing to release from a detached HEAD.'
}

$existingTag = Get-GitOutput @('tag', '--list', $tagName)
if ($existingTag) {
    throw "Tag '$tagName' already exists."
}

if (-not $SkipVersionCheck) {
    $pyproject = Get-Content -Raw -LiteralPath 'pyproject.toml'
    if ($pyproject -notmatch "version\s*=\s*`"$([regex]::Escape($plainVersion))`"") {
        throw "pyproject.toml version does not match $plainVersion. Update docs/version first, or pass -SkipVersionCheck for rehearsal only."
    }

    $readme = Get-Content -Raw -LiteralPath 'README.md'
    if ($readme -notmatch [regex]::Escape("version-$plainVersion-")) {
        throw "README.md badge does not match $plainVersion."
    }

    $readmeZh = Get-Content -Raw -LiteralPath 'README_ZH.md'
    if ($readmeZh -notmatch [regex]::Escape("version-$plainVersion-")) {
        throw "README_ZH.md badge does not match $plainVersion."
    }

    $changelog = Get-Content -Raw -LiteralPath 'CHANGELOG.md'
    if ($changelog -notmatch "(?m)^##\s+$([regex]::Escape($tagName))\b") {
        throw "CHANGELOG.md is missing a '$tagName' section."
    }
}

$fixturePaths = @(
    'tests/testdata/scoreboard_tb.vcd',
    'tests/testdata/fifo_latency_tb.vcd',
    'tests/testdata/fifo_occupancy_tb.vcd'
)
$backupRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("wavekit-release-" + [guid]::NewGuid().ToString('N'))

try {
    if (-not $DryRun) {
        foreach ($path in $fixturePaths) {
            Copy-IfExists -Source (Join-Path $repoRoot $path) -Destination (Join-Path $backupRoot $path)
        }
    }

    $oldPythonPath = $env:PYTHONPATH
    $srcPath = Join-Path $repoRoot 'src'
    $separator = [System.IO.Path]::PathSeparator
    $env:PYTHONPATH = if ($oldPythonPath) { "$srcPath$separator$oldPythonPath" } else { $srcPath }

    Invoke-External python @('tests/run_tests.py')

    if (-not $SkipPytest) {
        & python -m pytest --version *> $null
        if ($LASTEXITCODE -eq 0) {
            Invoke-External python @('-m', 'pytest', '-q')
        }
        elseif ($RequirePytest) {
            throw 'pytest is not available, and -RequirePytest was specified.'
        }
        else {
            Write-Warning 'pytest is not available; skipped optional python -m pytest -q.'
        }
    }
}
finally {
    if (-not $DryRun) {
        foreach ($path in $fixturePaths) {
            Restore-IfExists -Backup (Join-Path $backupRoot $path) -Destination (Join-Path $repoRoot $path)
        }
        if (Test-Path -LiteralPath $backupRoot) {
            Remove-Item -LiteralPath $backupRoot -Recurse -Force
        }
    }
}

if (-not $KeepGeneratedFixtureDates) {
    foreach ($path in $fixturePaths) {
        Clear-DateOnlyFixtureDiff -Path $path
    }
}

if (-not $NoStageAll) {
    Invoke-External git @('add', '--all')
}

$stagedFiles = Get-GitOutput @('diff', '--cached', '--name-only')
if ($stagedFiles) {
    $message = if ($CommitMessage) { $CommitMessage } else { "release: $tagName" }
    Invoke-External git @('commit', '-m', $message)
}
elseif (-not $AllowNoCommit) {
    throw 'No staged changes to commit. Pass -AllowNoCommit only when tagging the current HEAD intentionally.'
}

$finalTagMessage = if ($TagMessage) { $TagMessage } else { $tagName }
Invoke-External git @('tag', '-a', $tagName, '-m', $finalTagMessage)

Write-Host ''
if ($DryRun) {
    Write-Host "Dry run complete for $tagName on branch $branch. No commit or tag was created."
}
else {
    Write-Host "Created release tag $tagName on branch $branch."
    Write-Host "Push with: git push origin $branch --follow-tags"
}

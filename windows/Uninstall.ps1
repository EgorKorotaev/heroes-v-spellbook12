$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Spellbook12.psm1') -Force

function Uninstall-Spellbook12([string]$InstallRoot) {
    $state = Get-SpellbookInstallation $InstallRoot
    $game = $state.GameRoot
    Assert-SpellbookGameStopped $game
    $stage = Join-Path $game ('.spellbook12-uninstall-' + [Guid]::NewGuid().ToString('N'))
    $moved = New-Object 'System.Collections.Generic.List[object]'
    $complete = $false; $rollbackComplete = $false
    try {
        $null = [IO.Directory]::CreateDirectory($stage)
        $paths = @($state.Receipt.files | ForEach-Object { $_.path }) + 'Spellbook12/installation.json'
        foreach ($relative in $paths) {
            Assert-SpellbookDestination $relative -AllowShortcut
            $source = Join-SpellbookPath $game $relative
            $target = Join-SpellbookPath $stage $relative
            $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $target))
            [IO.File]::Move($source, $target)
            $moved.Add([PSCustomObject]@{ source = $source; target = $target })
        }
        $complete = $true
    } catch {
        for ($i = $moved.Count - 1; $i -ge 0; $i--) {
            [IO.File]::Move($moved[$i].target, $moved[$i].source)
        }
        $rollbackComplete = $true
        throw
    } finally {
        if (($complete -or $rollbackComplete) -and [IO.Directory]::Exists($stage)) {
            [IO.Directory]::Delete($stage, $true)
        }
    }
    # Delete only empty directories. Anything added by the player/AI is retained.
    $directories = @(Get-ChildItem -LiteralPath $InstallRoot -Directory -Recurse) |
        Sort-Object { $_.FullName.Length } -Descending
    foreach ($directory in $directories) {
        if (@(Get-ChildItem -LiteralPath $directory.FullName -Force).Count -eq 0) {
            [IO.Directory]::Delete($directory.FullName)
        }
    }
    if (@(Get-ChildItem -LiteralPath $InstallRoot -Force).Count -eq 0) { [IO.Directory]::Delete($InstallRoot) }
    return [PSCustomObject]@{ status = 'removed'; version = $state.Receipt.version; extra_files_retained = [IO.Directory]::Exists($InstallRoot) }
}

try { Uninstall-Spellbook12 $PSScriptRoot }
catch { Write-Host ('Removal stopped: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }

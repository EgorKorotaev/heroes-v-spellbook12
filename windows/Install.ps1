param([string]$GameRoot, [switch]$NoShortcut)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'payload/Spellbook12/Spellbook12.psm1') -Force

function Install-Spellbook12([string]$Destination, [switch]$SkipShortcut) {
    $release = Get-SpellbookRelease $PSScriptRoot
    $game = Select-SpellbookGameRoot $Destination
    $null = Assert-SpellbookGame $game $release
    Assert-SpellbookGameStopped $game
    $install = Join-Path $game 'Spellbook12'
    $resource = Join-Path $game 'data/Spellbook12.pak'
    $shortcut = Join-Path $game 'Spellbook12 - Play.lnk'
    foreach ($path in @($install, $resource)) {
        if (Test-Path -LiteralPath $path) { throw "Already present; remove the existing mod before installing: $path" }
    }
    if (-not $SkipShortcut -and (Test-Path -LiteralPath $shortcut)) {
        throw 'The requested shortcut already exists; it will not be overwritten'
    }
    foreach ($name in @('Spellbook12-grid.pak', 'Spellbook12-H55.pak', 'Spellbook7-probe.pak')) {
        if (Test-Path -LiteralPath (Join-Path $game ('data/' + $name))) {
            throw "An earlier spellbook package is installed: $name. Keep it backed up and remove it before installing this release."
        }
    }
    $stage = Join-Path $game ('.spellbook12-install-' + [Guid]::NewGuid().ToString('N'))
    $createdInstall = $false; $createdResource = $false; $createdShortcut = $false
    $owned = New-Object 'System.Collections.Generic.List[object]'
    try {
        $null = [IO.Directory]::CreateDirectory($stage)
        foreach ($file in @($release.files)) {
            $source = Join-SpellbookPath $PSScriptRoot $file.source
            $target = Join-SpellbookPath $stage $file.destination
            $null = [IO.Directory]::CreateDirectory((Split-Path -Parent $target))
            [IO.File]::Copy($source, $target, $false)
            Assert-SpellbookFile $target $file.sha256
            $owned.Add([PSCustomObject]@{ path = $file.destination; sha256 = $file.sha256 })
        }
        $releaseCopy = Join-Path $stage 'Spellbook12/release.json'
        [IO.File]::Copy((Join-Path $PSScriptRoot 'release.json'), $releaseCopy, $false)
        $owned.Add([PSCustomObject]@{ path = 'Spellbook12/release.json'; sha256 = (Get-SpellbookHash $releaseCopy) })
        [IO.Directory]::Move((Join-Path $stage 'Spellbook12'), $install)
        $createdInstall = $true
        [IO.File]::Move((Join-Path $stage 'data/Spellbook12.pak'), $resource)
        $createdResource = $true
        if (-not $SkipShortcut) {
            $shell = New-Object -ComObject WScript.Shell
            $link = $shell.CreateShortcut($shortcut)
            $link.TargetPath = Join-Path $install 'Launch.cmd'
            $link.WorkingDirectory = $install
            $link.IconLocation = (Join-SpellbookPath $game $release.engine.path) + ',0'
            $link.Description = 'Heroes V with the twelve-slot spellbook'
            $link.Save()
            $createdShortcut = $true
            $owned.Add([PSCustomObject]@{ path = 'Spellbook12 - Play.lnk'; sha256 = (Get-SpellbookHash $shortcut) })
        }
        $receipt = [ordered]@{
            schema = 1; package_id = $release.package_id; version = $release.version
            edition = $release.edition; installed_utc = [DateTime]::UtcNow.ToString('o')
            files = @($owned.ToArray())
        }
        $json = $receipt | ConvertTo-Json -Depth 8
        [IO.File]::WriteAllText((Join-Path $install 'installation.json'), $json, (New-Object Text.UTF8Encoding($false)))
        $null = Get-SpellbookInstallation $install
        return [PSCustomObject]@{ status = 'installed'; edition = $release.edition; version = $release.version; folder = $install }
    } catch {
        if ($createdShortcut -and [IO.File]::Exists($shortcut)) { [IO.File]::Delete($shortcut) }
        if ($createdResource -and [IO.File]::Exists($resource)) { [IO.File]::Delete($resource) }
        if ($createdInstall -and [IO.Directory]::Exists($install)) { [IO.Directory]::Delete($install, $true) }
        throw
    } finally {
        if ([IO.Directory]::Exists($stage)) { [IO.Directory]::Delete($stage, $true) }
    }
}

try {
    Install-Spellbook12 $GameRoot -SkipShortcut:$NoShortcut
    Write-Host 'Installed. Start the game with Spellbook12 - Play, or Spellbook12\Launch.cmd.'
} catch { Write-Host ('Installation stopped: ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:PackageId = 'heroes-v-spellbook12'
$script:KnownEngines = @{
    universe = @{
        path = 'bin/H5_Game.exe'
        sha256 = '88c9dc6107b9bced0649924a86360f1c56397ee00de0413f6f2b08f865ed5519'
    }
    h55 = @{
        path = 'bin/MMH55_64.exe'
        sha256 = '20210e51e39e61d0d0b40ed04321f3d01715b52abbe2b2fc2ed78f0453a55fac'
    }
}

function Read-SpellbookJson([string]$Path) {
    Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-SpellbookHash([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Join-SpellbookPath([string]$Root, [string]$Relative) {
    $name = $Relative.Replace('\', '/')
    if ([IO.Path]::IsPathRooted($name) -or $name -match '(^|/)\.\.?(/|$)' -or $name.Contains(':')) {
        throw "Invalid relative package path: $Relative"
    }
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $path = [IO.Path]::GetFullPath([IO.Path]::Combine($base, $name))
    if (-not $path.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Package path escapes its root: $Relative"
    }
    return $path
}

function Assert-SpellbookDestination([string]$Relative, [switch]$AllowShortcut) {
    $name = $Relative.Replace('\', '/')
    $allowed = $name.StartsWith('Spellbook12/', [StringComparison]::OrdinalIgnoreCase) -or
               $name -ceq 'data/Spellbook12.pak'
    if ($AllowShortcut -and $name -ceq 'Spellbook12 - Play.lnk') { $allowed = $true }
    if (-not $allowed -or [IO.Path]::GetExtension($name) -in @('.exe', '.dll')) {
        throw "Not a mod-owned destination: $Relative"
    }
}

function Assert-SpellbookFile([string]$Path, [string]$Sha256) {
    if ($Sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid SHA-256 in package metadata' }
    if (-not [IO.File]::Exists($Path)) { throw "Required file is missing: $Path" }
    if ((Get-SpellbookHash $Path) -cne $Sha256) { throw "File differs from its recorded version: $Path" }
}

function Assert-SpellbookGame([string]$GameRoot, $Release) {
    if (-not $script:KnownEngines.ContainsKey([string]$Release.edition)) { throw 'Unknown game edition' }
    $known = $script:KnownEngines[[string]$Release.edition]
    if ($Release.engine.path -cne $known.path -or $Release.engine.sha256 -cne $known.sha256) {
        throw 'The release does not describe a supported executable profile'
    }
    if (-not [IO.Directory]::Exists((Join-Path $GameRoot 'data'))) {
        throw 'Choose the game folder containing both bin and data'
    }
    $exe = Join-SpellbookPath $GameRoot $known.path
    Assert-SpellbookFile $exe $known.sha256
    return $exe
}

function Assert-SpellbookGameStopped([string]$GameRoot) {
    $bin = [IO.Path]::GetFullPath((Join-Path $GameRoot 'bin')).TrimEnd('\') + '\'
    $names = @('H5_Game', 'MMH55', 'MMH55_64', 'MMH55_Utility', 'MMH55_Utility_64')
    foreach ($process in @(Get-Process -Name $names -ErrorAction SilentlyContinue)) {
        try { $path = $process.Path } catch { continue }
        if ($path -and $path.StartsWith($bin, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Close this game before installing or removing Spellbook12'
        }
    }
}

function Get-SpellbookRelease([string]$PackageRoot) {
    $release = Read-SpellbookJson (Join-Path $PackageRoot 'release.json')
    if ($release.schema -ne 1 -or $release.package_id -cne $script:PackageId) {
        throw 'This is not a supported Spellbook12 package'
    }
    $destinations = @{}
    foreach ($file in @($release.files)) {
        Assert-SpellbookDestination $file.destination
        $target = Join-SpellbookPath $PackageRoot $file.destination
        if ($destinations.ContainsKey($target)) { throw 'Duplicate package destination' }
        $destinations[$target] = $true
        $source = Join-SpellbookPath $PackageRoot $file.source
        Assert-SpellbookFile $source $file.sha256
        if ((Get-Item -LiteralPath $source).Length -ne $file.bytes) { throw 'Package file size differs' }
    }
    if (-not (@($release.files | Where-Object { $_.destination -ceq 'data/Spellbook12.pak' }).Count -eq 1)) {
        throw 'The resource package is missing or duplicated'
    }
    return $release
}

function Get-SpellbookInstallation([string]$InstallRoot) {
    $receipt = Read-SpellbookJson (Join-Path $InstallRoot 'installation.json')
    if ($receipt.schema -ne 1 -or $receipt.package_id -cne $script:PackageId) {
        throw 'The installation receipt is not a supported Spellbook12 receipt'
    }
    $game = Split-Path -Parent ([IO.Path]::GetFullPath($InstallRoot))
    $seen = @{}
    foreach ($file in @($receipt.files)) {
        Assert-SpellbookDestination $file.path -AllowShortcut
        $path = Join-SpellbookPath $game $file.path
        if ($seen.ContainsKey($path)) { throw 'Duplicate path in installation receipt' }
        $seen[$path] = $true
        Assert-SpellbookFile $path $file.sha256
    }
    $release = Read-SpellbookJson (Join-Path $InstallRoot 'release.json')
    if ($release.package_id -cne $script:PackageId -or $release.version -cne $receipt.version) {
        throw 'The installed release and receipt do not match'
    }
    return [PSCustomObject]@{ GameRoot = $game; Release = $release; Receipt = $receipt }
}

function Select-SpellbookGameRoot([string]$Requested) {
    if ($Requested) { return (Get-Item -LiteralPath $Requested).FullName }
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose the Heroes V game folder containing bin and data'
    $dialog.ShowNewFolderButton = $false
    try {
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'Installation cancelled' }
        return $dialog.SelectedPath
    } finally { $dialog.Dispose() }
}

Export-ModuleMember -Function Read-SpellbookJson, Get-SpellbookHash, Join-SpellbookPath,
    Assert-SpellbookDestination, Assert-SpellbookFile, Assert-SpellbookGame,
    Assert-SpellbookGameStopped, Get-SpellbookRelease, Get-SpellbookInstallation,
    Select-SpellbookGameRoot

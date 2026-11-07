param(
    [Parameter(Mandatory=$true)][string]$UniversePackage,
    [Parameter(Mandatory=$true)][string]$H55Package,
    [Parameter(Mandatory=$true)][string]$UniverseExe,
    [Parameter(Mandatory=$true)][string]$H55Exe,
    [Parameter(Mandatory=$true)][string]$Report
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('Spellbook12-tests-' + [Guid]::NewGuid().ToString('N'))
$null = [IO.Directory]::CreateDirectory($scratch)
$checks = New-Object 'System.Collections.Generic.List[object]'

function Check([string]$Name, [bool]$Passed) {
    if (-not $Passed) { throw ('Failed check: ' + $Name) }
    $checks.Add([PSCustomObject]@{ name = $Name; status = 'passed' })
}
function Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }
function Run-Script([string]$Path, [string[]]$Arguments, [bool]$Success) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = (Join-Path $PSHOME 'powershell.exe')
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $quoted = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', $Path) + $Arguments |
        ForEach-Object { '"' + $_ + '"' }
    $info.Arguments = $quoted -join ' '
    $process = [Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit(30000)) { $process.Kill(); throw 'Test child timed out' }
    if (($process.ExitCode -eq 0) -ne $Success) {
        throw ('Unexpected child result: ' + $Path + ' / exit ' + $process.ExitCode + ' / ' + $stdout + ' / ' + $stderr)
    }
    return $process.ExitCode
}

try {
    $pairs = @(
        @{ edition = 'universe'; package = $UniversePackage; exe = $UniverseExe; name = 'H5_Game.exe' },
        @{ edition = 'h55'; package = $H55Package; exe = $H55Exe; name = 'MMH55_64.exe' }
    )
    foreach ($pair in $pairs) {
        # The game path includes spaces and Unicode, and the caller's CWD is elsewhere.
        $unicode = -join @([char]0x418,[char]0x433,[char]0x440,[char]0x430)
        $game = Join-Path $scratch ($unicode + ' ' + $pair.edition)
        $null = [IO.Directory]::CreateDirectory((Join-Path $game 'bin'))
        $null = [IO.Directory]::CreateDirectory((Join-Path $game 'data'))
        $null = [IO.Directory]::CreateDirectory((Join-Path $game 'Profiles'))
        $exe = Join-Path $game ('bin/' + $pair.name)
        [IO.File]::Copy($pair.exe, $exe)
        $base = Join-Path $game 'data/base-sentinel.pak'
        $save = Join-Path $game 'Profiles/player-save.sav'
        [IO.File]::WriteAllText($base, 'unrelated base data')
        [IO.File]::WriteAllText($save, 'unrelated player save')
        $before = @{ exe = (Hash $exe); base = (Hash $base); save = (Hash $save) }
        $install = Join-Path $pair.package 'Install.ps1'
        $app = Join-Path $game 'Spellbook12'
        $null = Run-Script $install @('-GameRoot', $game) $true
        Check ($pair.edition + '/install-unicode-path') ([IO.File]::Exists((Join-Path $app 'installation.json')))
        Check ($pair.edition + '/shortcut') ([IO.File]::Exists((Join-Path $game 'Spellbook12 - Play.lnk')))
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut((Join-Path $game 'Spellbook12 - Play.lnk'))
        Check ($pair.edition + '/shortcut-target') ($link.TargetPath -eq (Join-Path $app 'Launch.cmd'))
        $null = Run-Script (Join-Path $app 'Launch.ps1') @('-VerifyOnly') $true
        Check ($pair.edition + '/verify-installation-without-launch') $true
        $receiptHash = Hash (Join-Path $app 'installation.json')
        $null = Run-Script $install @('-GameRoot', $game, '-NoShortcut') $false
        Check ($pair.edition + '/duplicate-install-preserves-state') ((Hash (Join-Path $app 'installation.json')) -eq $receiptHash)
        $stub = Join-Path $app 'callbacks.bin'
        $stubBytes = [IO.File]::ReadAllBytes($stub)
        $changed = $stubBytes.Clone(); $changed[0] = $changed[0] -bxor 1
        [IO.File]::WriteAllBytes($stub, $changed)
        $null = Run-Script (Join-Path $app 'Launch.ps1') @('-VerifyOnly') $false
        Check ($pair.edition + '/modified-callbacks-block-launch') $true
        $null = Run-Script (Join-Path $app 'Uninstall.ps1') @() $false
        Check ($pair.edition + '/modified-file-blocks-all-removal') ([IO.File]::Exists((Join-Path $game 'data/Spellbook12.pak')) -and [IO.File]::Exists((Join-Path $app 'Launch.ps1')))
        [IO.File]::WriteAllBytes($stub, $stubBytes)
        # Permit hash reads but deny rename/delete, forcing a late move failure
        # after earlier owned files have already moved into the rollback stage.
        $resource = Join-Path $game 'data/Spellbook12.pak'
        $lock = [IO.File]::Open($resource, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            $null = Run-Script (Join-Path $app 'Uninstall.ps1') @() $false
            Check ($pair.edition + '/locked-resource-rolls-back-all-files') ((Hash (Join-Path $app 'installation.json')) -eq $receiptHash -and [IO.File]::Exists((Join-Path $app 'Launch.ps1')) -and [IO.File]::Exists($resource))
            Check ($pair.edition + '/successful-rollback-cleans-stage') (@(Get-ChildItem -LiteralPath $game -Directory -Force | Where-Object { $_.Name.StartsWith('.spellbook12-uninstall-') }).Count -eq 0)
        } finally { $lock.Dispose() }
        $null = Run-Script (Join-Path $app 'Launch.ps1') @('-VerifyOnly') $true
        Check ($pair.edition + '/rolled-back-installation-verifies') $true
        $extra = Join-Path $app 'player-note.txt'; [IO.File]::WriteAllText($extra, 'keep my file')
        $null = Run-Script (Join-Path $app 'Uninstall.ps1') @() $true
        Check ($pair.edition + '/uninstall-removes-owned-resource') (-not [IO.File]::Exists((Join-Path $game 'data/Spellbook12.pak')))
        Check ($pair.edition + '/uninstall-removes-shortcut') (-not [IO.File]::Exists((Join-Path $game 'Spellbook12 - Play.lnk')))
        Check ($pair.edition + '/uninstall-retains-extra-file') ([IO.File]::ReadAllText($extra) -ceq 'keep my file')
        Check ($pair.edition + '/exe-unchanged') ((Hash $exe) -eq $before.exe)
        Check ($pair.edition + '/base-and-save-unchanged') ((Hash $base) -eq $before.base -and (Hash $save) -eq $before.save)
        # Remove our preserved test note/directory before testing a fresh install refusal.
        [IO.File]::Delete($extra); [IO.Directory]::Delete($app)
        $exeBytes = [IO.File]::ReadAllBytes($exe)
        $badExe = $exeBytes.Clone(); $badExe[0] = $badExe[0] -bxor 1
        [IO.File]::WriteAllBytes($exe, $badExe)
        $null = Run-Script $install @('-GameRoot', $game, '-NoShortcut') $false
        Check ($pair.edition + '/unsupported-exe-no-install') (-not [IO.Directory]::Exists($app) -and -not [IO.File]::Exists((Join-Path $game 'data/Spellbook12.pak')))
        [IO.File]::WriteAllBytes($exe, $exeBytes)
        $legacy = Join-Path $game 'data/Spellbook12-grid.pak'; [IO.File]::WriteAllText($legacy, 'old mod sentinel')
        $null = Run-Script $install @('-GameRoot', $game, '-NoShortcut') $false
        Check ($pair.edition + '/legacy-package-preserved') ([IO.File]::ReadAllText($legacy) -ceq 'old mod sentinel')
        [IO.File]::Delete($legacy)
        # A modified release manifest may not target game executables.
        $badPackage = Join-Path $scratch ($pair.edition + '-bad-package')
        Copy-Item -LiteralPath $pair.package -Destination $badPackage -Recurse
        $metaPath = Join-Path $badPackage 'release.json'
        $meta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $meta.files[0].destination = 'bin/' + $pair.name
        [IO.File]::WriteAllText($metaPath, ($meta | ConvertTo-Json -Depth 12), (New-Object Text.UTF8Encoding($false)))
        $null = Run-Script (Join-Path $badPackage 'Install.ps1') @('-GameRoot', $game, '-NoShortcut') $false
        Check ($pair.edition + '/executable-destination-rejected') ((Hash $exe) -eq $before.exe -and -not [IO.Directory]::Exists($app))
    }
    $result = [ordered]@{ status = 'passed'; tests = $checks.Count; checks = @($checks.ToArray());
        PowerShell = $PSVersionTable.PSVersion.ToString(); game_started = $false; working_game_files_changed = $false }
    [IO.File]::WriteAllText($Report, ($result | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    Write-Output ('Windows installation checks passed: ' + $checks.Count)
} finally {
    if ((Split-Path -Leaf $scratch).StartsWith('Spellbook12-tests-')) { [IO.Directory]::Delete($scratch, $true) }
}

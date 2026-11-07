param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Spellbook12.psm1') -Force
$state = Get-SpellbookInstallation $PSScriptRoot
$gameRoot = $state.GameRoot
$exe = Assert-SpellbookGame $gameRoot $state.Release
$manifest = Read-SpellbookJson (Join-Path $PSScriptRoot 'runtime-patch.json')
if ($manifest.source_sha256 -cne $state.Release.engine.sha256 -or $manifest.slots_per_spread -ne 12) {
    throw 'The native profile and installed game edition do not match'
}
if ($VerifyOnly) {
    [PSCustomObject]@{ status = 'verified'; version = $state.Release.version; edition = $state.Release.edition; game_started = $false }
    return
}
Assert-SpellbookGameStopped $gameRoot
function Bytes([string]$hex) {
    $b=New-Object byte[] ($hex.Length/2)
    for ($i=0;$i -lt $b.Length;$i++) { $b[$i]=[Convert]::ToByte($hex.Substring(2*$i,2),16) }
    return ,$b
}
function Verify([long]$address,[byte[]]$expected) {
    $read=[IntPtr]::Zero
    $actual=New-Object byte[] $expected.Length
    if (-not [Spellbook12Memory]::ReadProcessMemory($handle,[IntPtr]$address,$actual,$actual.Length,[ref]$read)) { throw 'ReadProcessMemory failed' }
    if ($read.ToInt64() -ne $expected.Length) { throw 'Incomplete process-memory read' }
    if ([BitConverter]::ToString($actual) -ne [BitConverter]::ToString($expected)) {
        throw ('Unexpected live bytes at 0x{0:x}: {1}' -f $address,[BitConverter]::ToString($actual))
    }
}
function Set-ProbeBytes([long]$address,[byte[]]$b) {
    $old=[uint32]0
    $length=[UIntPtr]::new([uint64]$b.Length)
    if (-not [Spellbook12Memory]::VirtualProtectEx($handle,[IntPtr]$address,$length,0x40,[ref]$old)) { throw 'VirtualProtectEx failed' }
    try {
        $written=[IntPtr]::Zero
        if (-not [Spellbook12Memory]::WriteProcessMemory($handle,[IntPtr]$address,$b,$b.Length,[ref]$written)) { throw 'WriteProcessMemory failed' }
        if ($written.ToInt64() -ne $b.Length) { throw 'Short process-memory write' }
        [Spellbook12Memory]::FlushInstructionCache($handle,[IntPtr]$address,$length) | Out-Null
        Verify $address $b
    } finally {
        $discard=[uint32]0
        [Spellbook12Memory]::VirtualProtectEx($handle,[IntPtr]$address,$length,$old,[ref]$discard) | Out-Null
    }
}

$gameProcess = $null
$handle = [IntPtr]::Zero
try {
    Write-Host 'Preparing the twelve-slot spellbook. Wait for the ready message before starting or loading a game.'
    $gameProcess = Start-Process -FilePath $exe -WorkingDirectory (Join-Path $gameRoot 'bin') -PassThru
    # Retain the proven initialization interval; no window/profile settings change.
    Start-Sleep -Seconds 8
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        $gameProcess.Refresh()
        if ($gameProcess.HasExited) { throw 'The game exited during normal startup; check whether it starts without the mod' }
        if ($gameProcess.MainWindowHandle -ne 0) { break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($gameProcess.MainWindowHandle -eq 0) { throw 'The game did not create its window' }
    # Match the previously validated startup order: initialize the game, then compile interop.
    Add-Type @'
    using System;
    using System.Runtime.InteropServices;
    public static class Spellbook12Memory {
     [DllImport("kernel32.dll",SetLastError=true)] public static extern IntPtr OpenProcess(uint access,bool inherit,int pid);
     [DllImport("kernel32.dll",SetLastError=true)] public static extern bool ReadProcessMemory(IntPtr h,IntPtr address,byte[] b,int n,out IntPtr read);
     [DllImport("kernel32.dll",SetLastError=true)] public static extern bool WriteProcessMemory(IntPtr h,IntPtr address,byte[] b,int n,out IntPtr written);
     [DllImport("kernel32.dll",SetLastError=true)] public static extern bool VirtualProtectEx(IntPtr h,IntPtr address,UIntPtr n,uint flags,out uint old);
     [DllImport("kernel32.dll",SetLastError=true)] public static extern IntPtr VirtualAllocEx(IntPtr h,IntPtr address,UIntPtr n,uint allocation,uint protection);
     [DllImport("kernel32.dll")] public static extern bool FlushInstructionCache(IntPtr h,IntPtr address,UIntPtr n);
     [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
    }
'@
    $handle = [Spellbook12Memory]::OpenProcess(0x38, $false, $gameProcess.Id)
    if ($handle -eq [IntPtr]::Zero) { throw 'Cannot open the supported game process' }
    # Check every target before changing anything. These instructions belong only
    # to the spellbook; the game must still be in its menu when this is applied.
    foreach ($p in $manifest.patches) { Verify ([Convert]::ToInt64($p.va.Substring(2),16)) (Bytes $p.before) }
    Verify $manifest.hook_va (Bytes $manifest.hook_before)
    foreach ($hook in $manifest.extra_hooks) {
        Verify ([Convert]::ToInt64($hook.va.Substring(2),16)) (Bytes $hook.before)
    }
    $stub=[IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'callbacks.bin'))
    $allocation=[Spellbook12Memory]::VirtualAllocEx($handle,[IntPtr]0x18000000,[UIntPtr]::new([uint64]4096),0x3000,0x40)
    if ($allocation -eq [IntPtr]::Zero) {
        $allocation=[Spellbook12Memory]::VirtualAllocEx($handle,[IntPtr]::Zero,[UIntPtr]::new([uint64]4096),0x3000,0x40)
    }
    if ($allocation -eq [IntPtr]::Zero) { throw ('Cannot allocate native callback code: '+[Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
    $va=$allocation.ToInt64()
    foreach ($r in $manifest.relocations) {
        $relative=[BitConverter]::GetBytes([int]($r.target-$va-$r.offset-5))
        [Array]::Copy($relative,0,$stub,([int]$r.offset+1),4)
    }
    Set-ProbeBytes $va $stub
    foreach ($p in $manifest.patches) { Set-ProbeBytes ([Convert]::ToInt64($p.va.Substring(2),16)) (Bytes $p.after) }
    $jmp=New-Object byte[] 5
    $jmp[0]=0xe9
    [Array]::Copy([BitConverter]::GetBytes([int]($va-$manifest.hook_va-5)),0,$jmp,1,4)
    Set-ProbeBytes $manifest.hook_va $jmp
    foreach ($hook in $manifest.extra_hooks) {
        $address=[Convert]::ToInt64($hook.va.Substring(2),16)
        $b=New-Object byte[] ($hook.before.Length/2)
        for ($i=0;$i -lt $b.Length;$i++) { $b[$i]=0x90 }
        $b[0]=0xe9
        [Array]::Copy([BitConverter]::GetBytes([int]($va+$hook.stub_offset-$address-5)),0,$b,1,4)
        Set-ProbeBytes $address $b
    }
    Write-Output ('{0}-spell spread applied to game process {1}; callback at 0x{2:x}' -f $manifest.slots_per_spread,$gameProcess.Id,$va)
    Write-Host 'Spellbook12 is ready.'
} catch {
    # A failed partial application must not leave our newly launched game running.
    if ($null -ne $gameProcess -and -not $gameProcess.HasExited) { $gameProcess.Kill() }
    throw
} finally {
    if ($handle -ne [IntPtr]::Zero) { [Spellbook12Memory]::CloseHandle($handle) | Out-Null }
}

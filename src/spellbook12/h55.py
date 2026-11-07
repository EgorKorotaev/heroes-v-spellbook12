"""Port the approved callbacks to exact MMH55 engine profiles."""
import copy
import hashlib
import struct
import pefile

BASE_STUB_SHA = '548ea0a99371d7da51dff0e8e8ca240f5ef3c901ce631a0a66e2b3cd49d8fb92'
EXES = {
    'MMH55_64.exe': '20210e51e39e61d0d0b40ed04321f3d01715b52abbe2b2fc2ed78f0453a55fac',
    'MMH55.exe': 'd1a0e6173883704b7b6a309ff37d7bbcc806e159c13a74580dd6924b23b77baf',
    'MMH55_Utility_64.exe': '3d2e26d352002f62c9f09b12d58bd0a5e1ede8be702b1ad3a6ce8722629fcf6c',
    'MMH55_Utility.exe': '7c01933eacc8138261b8a82d24ccb29e4a9ebd4e47656fe62befd7888a87fd69',
}
# Reviewed instruction sites, not a constant relocation of the old EXE.
SITES = {
    0x682afb: 0x65652b, 0x683a5e: 0x65754e, 0x6847fa: 0x6582ca,
    0x68604f: 0x659b1f, 0x686056: 0x659b26, 0x686095: 0x659b65,
    0x686b75: 0x65a645, 0x68302b: 0x656a5b, 0x687077: 0x65aa56,
    0x683331: 0x656d4c, 0x683cf3: 0x6577e2, 0x683b73: 0x657662,
    0x8904e1: 0xcb0191, 0x6835a5: 0x656fca,
}
TARGETS = {
    0x401ab0: 0x401070, 0x687890: 0x65b290, 0x687ef0: 0x65bc70,
    0x879240: 0x40c830, 0x68707c: 0x65aa5b,
    0xcf60a0: 0x837260, 0xcf7ac0: 0x838bc0,
    0x683337: 0x656d52, 0x683cf8: 0x6577e7,
    0x683b79: 0x657668, 0x8904e7: 0xcb0197, 0x6835ab: 0x656fd0,
}
# RC19k main engine uses a 768-unit UI height and separate render dimensions.
# Constants are in read-only PE data and checked before building.
GLOBALS = {
    0xe30b64: 0xe2713c, 0xe30b74: 0xe271c8,
    0xfdd78c: 0xfbd67c,
    0xf74bf0: 0xf7b53c, 0xf74bf4: 0xf7b540,
    0xf74be0: 0xf7b530, 0xf74be4: 0xe2fad5,
    0x10268c4: 0x10f0e64, 0x10268c8: 0x10f0e68,
    0xe44660: 0xebb2a0, 0xe0ab70: 0xe08800,
    0x683a10: 0x657500, 0x683025: 0x656a55, 0x684d77: 0x658846,
}


def read(pe, address, length):
    return pe.get_data(address - pe.OPTIONAL_HEADER.ImageBase, length)


def replace_once(code, before, after):
    assert len(before) == len(after)
    assert code.count(before) == 1, (before.hex(), code.count(before))
    at = code.index(before)
    code[at:at+len(before)] = after


def build_h55_profile(source,original_manifest,original_stub,name='MMH55_64.exe'):
    if name not in EXES:raise ValueError('Unknown MMH55 engine profile: '+name)
    digest=EXES[name]
    if hashlib.sha256(original_stub).hexdigest()!=BASE_STUB_SHA:
        raise ValueError('Canonical callbacks changed; review the H55 port before building')
    if len(original_stub)!=1280:raise ValueError('Unexpected canonical callback size')
    assert hashlib.sha256(source).hexdigest() == digest, name
    pe = pefile.PE(data=source, fast_load=True)
    assert pe.FILE_HEADER.Machine == 0x14c
    assert pe.OPTIONAL_HEADER.ImageBase == 0x400000
    manifest = copy.deepcopy(original_manifest)
    code = bytearray(original_stub)
    main = 'Utility' not in name
    if main:
        assert read(pe, GLOBALS[0xe30b64], 13) == b'MB_CastSpell\0'
        assert read(pe, GLOBALS[0xe30b74], 16) == b'MB_Button_School'
        for address, value in ((0xe2fad5, 768.), (0xebb2a0, 4/3), (0xe08800, .5)):
            assert read(pe, address, 4) == struct.pack('<f', value)
        # Rewrite known absolute operands, preserving all relative internal
        # branches, call/pop tables and geometry-derived coefficients.
        offsets = []
        for old, new in GLOBALS.items():
            needle = struct.pack('<I', old)
            hits = [i for i in range(len(code)-3) if code[i:i+4] == needle]
            assert hits, hex(old)
            offsets.extend((i, old, new) for i in hits)
        assert len({i for i, _, _ in offsets}) == len(offsets)
        for at, old, new in offsets:
            struct.pack_into('<I', code, at, new)
        # Unlike the 3.1 camera, this engine builds a fixed 1024x768 book
        # projection. Its normalized coordinates stretch with the viewport:
        # horizontal factor UI width, vertical factor UI height * 4/3.
        old_scale = bytes.fromhex(
            'd90540b5f700d80da0b2eb00d9053cb5f700dff17308ddd8d9053cb5f700'
            'd9c0d80d30b5f700d8353cb5f700d91c24'
            'd80dd5fae200d83540b5f700d95c2404')
        new_scale = bytes.fromhex('d90530b5f700d91c24d905d5fae200d80da0b2eb00d95c2404')
        replace_once(code, old_scale, new_scale + b'\x90'*(len(old_scale)-len(new_scale)))
        # The 3.0 picker keeps the selected material in EBX, not EBP.
        pick = manifest['extra_hooks'][-1]['stub_offset']
        tail = bytearray(code[pick:])
        replace_once(tail, bytes.fromhex('9c608bc5'), bytes.fromhex('9c608bc3'))
        replace_once(tail, bytes.fromhex('c7442408ffffffff'), bytes.fromhex('c7442410ffffffff'))
        replace_once(tail, bytes.fromhex('619d8b8eb8010000'), bytes.fromhex('619d8b8eb0010000'))
        code[pick:] = tail
        for patch in manifest['patches']:
            patch['va'] = hex(SITES[int(patch['va'], 16)])
        # 3.0 additionally clips clicks against six obsolete, cached 2D
        # rectangles. Our real mesh/ray filter already supplies all twelve
        # active regions; retaining the old check would reject new slots.
        manifest['patches'].append({
            'va': '0x657007', 'before': '0f84cf000000',
            'after': 'e9d000000090',
            'reason': 'use native mesh hit and twelve-slot margin filter instead of six legacy click rectangles',
        })
        manifest['hook_va'] = SITES[manifest['hook_va']]
        manifest['hook_before'] = '68c871e200'
        for hook in manifest['extra_hooks']:
            hook['va'] = hex(SITES[int(hook['va'], 16)])
            if hook['va'] == '0x656d4c': hook['before'] = '8b1d7cd6fb00'
            if hook['va'] == '0x656fca': hook['before'] = '8b8eb0010000'
        for relocation in manifest['relocations']:
            relocation['target'] = TARGETS[relocation['target']]
        manifest['port_globals'] = {hex(k): hex(v) for k, v in GLOBALS.items()}
    # Verify all sites on disk before emitting any runnable profile.
    for patch in manifest['patches'] + manifest['extra_hooks']:
        assert read(pe, int(patch['va'], 16), len(patch['before'])//2) == bytes.fromhex(patch['before']), patch
    assert read(pe, manifest['hook_va'], 5) == bytes.fromhex(manifest['hook_before'])
    manifest.update(source_sha256=digest, executable='bin\\'+name,
                    engine='MMH55 main / Quantomas' if main else 'MMH55 Utility',
                    port_source_stub_sha256=hashlib.sha256(original_stub).hexdigest())
    manifest['projection'] = 'fixed 4:3' if main else 'native 3.1 adaptive'
    return manifest,bytes(code)

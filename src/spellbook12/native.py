"""Build the reviewed book callbacks and declarative runtime patches.

Only patch metadata and our callback bytes are emitted. No game EXE is written.
"""
import hashlib
import struct
import pefile
from .geometry import decode, spell_anchor_coefficients
from .resources import (SLOTS, FRONT_PARTS, BACK_PARTS, BOOK_WIDTH, BOOK_HEIGHT,
    OUTLINER_WIDTH, OUTLINER_HEIGHT, OVERLAY_LIFT, FIXED_OVERLAY_LIFT,
    COLUMN_U_SCALE, CONTENT_REFERENCE_WIDTH, CAST_X_BOUNDS, BUTTON_DEPTH_FRACTION,
    BOOK_CAMERA_EYE, SPELL_TOOLTIP_PARTS, TEXT_LEFT, TEXT_TOP, TEXT_WIDTH,
    ICON_TOP, ICON_BOTTOM, NEW_UID, PAPER_HALF_THICKNESS)

UNIVERSE_SHA256 = '88c9dc6107b9bced0649924a86360f1c56397ee00de0413f6f2b08f865ed5519'

def build_native(resource_payload, spell_anchors=None):
    changes=[]
    def change(va,before,after,reason):
        assert len(before)==len(after)
        changes.append({'va':hex(va),'before':before.hex(),'after':after.hex(),'reason':reason})
    for va, before, after, reason in (
        (0x682afb, '83c606', '83c60c', 'next-page availability'),
        (0x683a5e, '83c706', '83c70c', 'next-page presentation'),
        (0x6847fa, '83f806', '83f80c', 'visible spell slice size'),
        (0x68604f, '83c206', '83c20c', 'next-page bound'),
        (0x686056, '830606', '83060c', 'next-page increment'),
        (0x686095, '8300fa', '8300f4', 'previous-page decrement'),
        (0x686b75, '83fa18', '83fa30', 'accept twelve material bindings'),
        # ESI advances by 12-byte outliner records; EBX by 4-byte handles.
        # Compare the handle offset with 12*4 so the immediate stays signed-8 safe.
        (0x68302b, '83fe48', '83fb30', 'clear hover highlighting across all twelve slots'),
    ):
        change(va, bytes.fromhex(before), bytes.fromhex(after), reason)
    instruction_patches = list(changes)
    # Additional native cast descriptors for spell ordinals 6..11.
    # Keep the original register context and execute the displaced push on return.
    stub_va = 0x11da000
    code = bytearray.fromhex('9c6083ec50')  # pushfd; pushad; scratch frame
    relocations=[]
    def call(va):
        relocations.append({'offset':len(code),'target':va})
        code.extend(b'\xe8'+struct.pack('<i', va-(stub_va+len(code)+5)))
    def push(va):
        code.extend(b'\x68'+struct.pack('<I',va))
    for index in range(6,SLOTS):
        push(0xe30b64)  # MB_CastSpell
        code.extend(bytes.fromhex('8d4c2404'))
        call(0x401ab0)  # native string constructor
        code.extend(bytes.fromhex('6a006a006a006a006a')+bytes([index]))
        code.extend(bytes.fromhex('8d442414506a')+bytes([FRONT_PARTS[index]]))
        code.extend(bytes.fromhex('8d4c2434'))
        call(0x687890)  # descriptor(part, name, index, rect)
        code.extend(bytes.fromhex('508bce'))
        call(0x687ef0)  # append to existing native interaction vector
        code.extend(bytes.fromhex('8b44241c50'))
        call(0x879240)  # descriptor string storage
        code.extend(bytes.fromhex('83c4048b042450'))
        call(0x879240)  # source string storage
        code.extend(bytes.fromhex('83c404'))
    code.extend(bytes.fromhex('83c450619d'))
    push(0xe30b74)  # displaced instruction
    relocations.append({'offset':len(code),'target':0x68707c})
    code.extend(b'\xe9'+struct.pack('<i',0x68707c-(stub_va+len(code)+5)))
    change(0x687077, bytes.fromhex('68740be300'), b'\xe9'+struct.pack('<i',stub_va-0x68707c), 'register native cast interactions 7..12')
    # Widen the book camera before the native view/inverse matrices are built.
    # Rendering, mesh picking and projected tooltip bounds share this camera.
    camera_offset = len(code)
    code.extend(bytes.fromhex('9c60'))  # preserve flags and general registers
    push(struct.unpack('<I',struct.pack('<f',BOOK_WIDTH))[0])
    code.extend(bytes.fromhex('d907d80c24d91f'))
    code.extend(bytes.fromhex('c70424')+struct.pack('<f',BOOK_HEIGHT))
    code.extend(bytes.fromhex('d94714d80c24d95f1483c404'))
    code.extend(bytes.fromhex('8bd78d4f40'))  # inverse projection must match picking
    call(0xcf60a0)
    code.extend(bytes.fromhex('8bcf'))
    call(0xcf7ac0)  # rebuild cached frustum after the projection change
    code.extend(bytes.fromhex('619d'))
    code.extend(bytes.fromhex('8b1d8cd7fd00'))  # displaced mov ebx,[...]
    relocations.append({'offset':len(code),'target':0x683337})
    code.extend(b'\xe9'+struct.pack('<i',0x683337-(stub_va+len(code)+5)))
    camera_hook = {'va':'0x683331','before':'8b1d8cd7fd00','stub_offset':camera_offset}
    change(0x683331,bytes.fromhex(camera_hook['before']),
           b'\xe9'+struct.pack('<i',stub_va+camera_offset-0x683336)+b'\x90',
           'widen original book camera, preserving native animation and picking')
    # Native controls project model bounds; vanilla spell descriptions use
    # their separate icon-preset route below.
    # The original projection produces render pixels. Tooltip layout consumes
    # UI units, as in b29220: p/render*ui + offset (extents omit the offset).
    # Convert before the native selected-bookmark inset is applied in UI units.
    tooltip_offset = len(code)
    code.extend(bytes.fromhex('9c608bf0813e00000080'))
    sentinel_branches=[]
    sentinel_branches.append(len(code));code.extend(bytes.fromhex('7400'))
    code.extend(bytes.fromhex('817e0400000080'))
    sentinel_branches.append(len(code));code.extend(bytes.fromhex('7400'))
    for offset,axis in ((0,0),(4,1),(8,0),(12,1)):
        code.extend(bytes((0xdb,0x46,offset)))  # fild [esi+offset]
        code.extend(bytes.fromhex('d835')+struct.pack('<I',0xf74bf0+4*axis))
        code.extend(bytes.fromhex('d80d')+struct.pack('<I',0xf74be0+4*axis))
        if offset<8:
            code.extend(bytes.fromhex('d805')+struct.pack('<I',0x10268c4+4*axis))
        code.extend(bytes((0xdb,0x5e,offset)))  # fistp [esi+offset]
    tooltip_restore=len(code)
    for at in sentinel_branches:
        delta=tooltip_restore-at-2
        assert 0<=delta<=127
        code[at+1]=delta
    code.extend(bytes.fromhex('619d3b77108b10'))
    relocations.append({'offset':len(code),'target':0x683cf8})
    code.extend(b'\xe9'+struct.pack('<i',0x683cf8-(stub_va+len(code)+5)))
    tooltip_hook = {'va':'0x683cf3','before':'3b77108b10','stub_offset':tooltip_offset}
    change(0x683cf3,bytes.fromhex(tooltip_hook['before']),
           b'\xe9'+struct.pack('<i',stub_va+tooltip_offset-0x683cf8),
           'convert native part tooltip bounds from render pixels to UI coordinates')
    # Vanilla spells have their own stable icon rectangles, separate from model
    # button bounds. Rebuild all twelve presets from actual fixed-leaf UVs.
    spell_parts=list(SPELL_TOOLTIP_PARTS)
    if spell_anchors is None:
        spell_anchors=spell_anchor_coefficients(
            decode(resource_payload['bin/Geometries/'+NEW_UID]),spell_parts,
            (OUTLINER_WIDTH,OUTLINER_HEIGHT),
            (OUTLINER_WIDTH//2-64,OUTLINER_WIDTH//2+64,ICON_TOP,ICON_BOTTOM),
            (BOOK_WIDTH,BOOK_HEIGHT))
    if len(spell_anchors)!=12 or any(len(row)!=4 for row in spell_anchors):
        raise ValueError('Exactly twelve centre/half-size tooltip anchors are required')
    spell_tooltip_offset=len(code)
    code.extend(bytes.fromhex('8b471083f80c720b8b471c034714'))
    relocations.append({'offset':len(code),'target':0x683b79})
    code.extend(b'\xe9'+struct.pack('<i',0x683b79-(stub_va+len(code)+5)))
    code.extend(bytes.fromhex('83ec08e800000000'))
    spell_tip_base=len(code)
    code.extend(bytes.fromhex('5ac1e0048db402'))
    spell_tip_table_fix=len(code);code.extend(b'\0'*4)
    code.extend(bytes.fromhex('8b8c24f4060000'))
    code.extend(bytes.fromhex('d905f44bf700d80d6046e400d905f04bf700dff17308ddd8d905f04bf700'))
    code.extend(bytes.fromhex('d9c0d80de04bf700d835f04bf700d91c24'))
    code.extend(bytes.fromhex('d80de44bf700d835f44bf700d95c2404'))
    for offset,axis in ((0,0),(4,1),(8,0),(12,1)):
        code.extend(bytes((0xd9,0x44,0x24,axis*4,0xd8,0x4e,offset)))
        if offset<8:
            code.extend(bytes.fromhex('d905')+struct.pack('<I',0xf74be0+4*axis))
            code.extend(bytes.fromhex('d80d70abe000dec1d805')+struct.pack('<I',0x10268c4+4*axis))
        code.extend(bytes((0xdb,0x59,offset)))
    code.extend(bytes.fromhex('c74110000000008bc183c4085f5e5b81c4dc060000c20800'))
    while len(code)%4:code.append(0)
    spell_tip_table=len(code)
    for row in spell_anchors:code.extend(struct.pack('<4f',*row))
    struct.pack_into('<i',code,spell_tip_table_fix,spell_tip_table-spell_tip_base)
    spell_tooltip_hook={'va':'0x683b73','before':'8b471c034714','stub_offset':spell_tooltip_offset}
    change(0x683b73,bytes.fromhex(spell_tooltip_hook['before']),
           b'\xe9'+struct.pack('<i',stub_va+spell_tooltip_offset-0x683b78)+b'\x90',
           'restore vanilla spell-tooltip path with twelve geometry-derived icon rectangles')
    # The outliner normally wraps at canvas width minus text origin. Restrict
    # this to TEXT_WIDTH only for the spell-card callers, preserving other UI
    # text and the book's separate mana parchment. At this point ESP+0x50 is
    # the return address of COutliner::SetData; PUSHFD shifts it to +0x54.
    wrap_offset = len(code)
    code.extend(bytes.fromhex('9c'))
    branches=[]
    for caller in (0x683a10,0x683025,0x684d77):
        code.extend(bytes.fromhex('817c2454')+struct.pack('<I',caller))
        branches.append(len(code))
        code.extend(bytes.fromhex('7400'))
    code.extend(bytes.fromhex('9ddb4424388b17'))
    relocations.append({'offset':len(code),'target':0x8904e7})
    code.extend(b'\xe9'+struct.pack('<i',0x8904e7-(stub_va+len(code)+5)))
    book_wrap=len(code)
    for branch in branches:
        code[branch+1]=book_wrap-(branch+2)
    push(TEXT_LEFT+TEXT_WIDTH)
    code.extend(bytes.fromhex('db042483c4049d8b17'))
    relocations.append({'offset':len(code),'target':0x8904e7})
    code.extend(b'\xe9'+struct.pack('<i',0x8904e7-(stub_va+len(code)+5)))
    wrap_hook={'va':'0x8904e1','before':'db4424388b17','stub_offset':wrap_offset}
    change(0x8904e1,bytes.fromhex(wrap_hook['before']),
           b'\xe9'+struct.pack('<i',stub_va+wrap_offset-0x8904e6)+b'\x90',
           'wrap spell-card labels to their visible text band; scope by native caller')
    # Filter only spell surfaces after native mesh picking. Ray direction X times
    # the reported distance gives hit X relative to the book camera's origin.
    # At this point EBP is the picked material; EDI optionally receives that ID.
    # Keep native picking/cleanup for arrows, tabs, close and all rejected hits.
    pick_offset=len(code)
    code.extend(bytes.fromhex('9c608bc583f826'))
    short=[];labels={}
    def jump8(op,label):
        short.append((len(code),label));code.extend(bytes((op,0)))
    jump8(0x73,'restore')
    code.extend(bytes.fromhex('e800000000'))
    pick_base=len(code)
    code.extend(bytes.fromhex('5a0fb68402'))
    map_fix=len(code);code.extend(b'\0'*4)
    code.extend(bytes.fromhex('3cff'))
    jump8(0x74,'restore')
    code.extend(bytes.fromhex('c1e003d9442474d88c2480000000d98402'))
    lower_fix=len(code);code.extend(b'\0'*4)
    code.extend(bytes.fromhex('dff1'))
    jump8(0x7a,'reject');jump8(0x77,'reject')
    code.extend(bytes.fromhex('d98402'))
    upper_fix=len(code);code.extend(b'\0'*4)
    code.extend(bytes.fromhex('dff1'))
    jump8(0x7a,'reject');jump8(0x72,'reject')
    code.extend(bytes.fromhex('ddd8'))
    jump8(0xeb,'restore')
    labels['reject']=len(code)
    code.extend(bytes.fromhex('ddd8c7442408ffffffff85ff'))
    jump8(0x74,'restore')
    code.extend(bytes.fromhex('c707ffffffff'))
    labels['restore']=len(code)
    code.extend(bytes.fromhex('619d8b8eb8010000'))
    relocations.append({'offset':len(code),'target':0x6835ab})
    code.extend(b'\xe9'+struct.pack('<i',0x6835ab-(stub_va+len(code)+5)))
    for at,label in short:
        delta=labels[label]-at-2
        assert -128<=delta<=127
        code[at+1]=delta&255
    part_columns=[255]*38
    for table in (FRONT_PARTS,BACK_PARTS):
        for slot,part in enumerate(table):part_columns[part]=(slot//6)*2+slot%2
    map_at=len(code);code.extend(bytes(part_columns))
    while len(code)%4:code.append(0)
    bounds_at=len(code)
    for lower,upper in CAST_X_BOUNDS:code.extend(struct.pack('<2f',lower,upper))
    for at,target in ((map_fix,map_at),(lower_fix,bounds_at),(upper_fix,bounds_at+4)):
        struct.pack_into('<i',code,at,target-pick_base)
    pick_hook={'va':'0x6835a5','before':'8b8eb8010000','stub_offset':pick_offset}
    change(0x6835a5,bytes.fromhex(pick_hook['before']),
           b'\xe9'+struct.pack('<i',stub_va+pick_offset-0x6835aa)+b'\x90',
           'exclude blank horizontal spell margins independently of rendered labels')
    manifest={
        'source_sha256':UNIVERSE_SHA256,'slots_per_spread':SLOTS,
        'book_scale':[BOOK_WIDTH,BOOK_HEIGHT],'outliner_size':[OUTLINER_WIDTH,OUTLINER_HEIGHT],
        'overlay_lift':OVERLAY_LIFT,'fixed_overlay_lift':FIXED_OVERLAY_LIFT,
        'paper_half_thickness':PAPER_HALF_THICKNESS,
        'within_sheet_u_scale':COLUMN_U_SCALE,'content_reference_book_width':CONTENT_REFERENCE_WIDTH,
        'cast_x_bounds':CAST_X_BOUNDS,'cast_icon_horizontal_padding':24,
        'button_depth_fraction':BUTTON_DEPTH_FRACTION,'book_camera_eye':BOOK_CAMERA_EYE,
        'button_picking':'native mesh and selector; perspective-preserving depth correction',
        'spell_tooltip_parts':spell_parts,'spell_tooltip_anchors':spell_anchors,
        'text_layout':{'left':TEXT_LEFT,'top':TEXT_TOP,'width':TEXT_WIDTH,'native_wrap':True},
        'patches':instruction_patches,'hook_va':0x687077,'hook_before':'68740be300',
        'extra_hooks':[camera_hook,tooltip_hook,spell_tooltip_hook,wrap_hook,pick_hook],
        'relocations':relocations}
    return manifest,bytes(code)


def validate_executable(source,manifest):
    if hashlib.sha256(source).hexdigest()!=manifest['source_sha256']:
        raise ValueError('Unsupported game executable SHA-256')
    pe=pefile.PE(data=source,fast_load=True)
    if pe.FILE_HEADER.Machine!=0x14c or pe.OPTIONAL_HEADER.ImageBase!=0x400000:
        raise ValueError('The profile requires the reviewed x86 image layout')
    sites=manifest['patches']+manifest['extra_hooks']+[
        {'va':hex(manifest['hook_va']),'before':manifest['hook_before']}]
    for site in sites:
        expected=bytes.fromhex(site['before'])
        actual=pe.get_data(int(site['va'],16)-pe.OPTIONAL_HEADER.ImageBase,len(expected))
        if actual!=expected:raise ValueError('Unexpected instruction bytes at '+site['va'])
    return len(sites)

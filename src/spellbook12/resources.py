"""Generate the approved book resources from a local game archive."""
import copy
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zipfile
from .geometry import Record, decode, encode, meshes, split_columns, widen_label_uv, lift_surface, project_forward, conform_paper

GEOM_UID = '5664D6D4-C7E3-4B01-9B25-C7931783C126'
NEW_UID = '271579D1-7C9A-4B71-9B00-000000000012'
MODEL_DIR = '_(Model)/Interface/SpellBook2/'
SLOTS = 12
FRONT_PARTS = [10,26,11,27,12,28,2,29,3,30,4,31]
BACK_PARTS = [5,32,1,33,6,34,7,35,8,36,9,37]
BOOK_WIDTH = 1.25
BOOK_HEIGHT = 1.05
# Keep the accepted 115x105 content size and column separation while enlarging
# the paper margins. U coordinates scale about the middle of each physical leaf.
CONTENT_REFERENCE_WIDTH = 1.15
COLUMN_U_SCALE = BOOK_WIDTH / CONTENT_REFERENCE_WIDTH
# Only the turning leaf needs the extra separation. Raising the fixed leaves
# makes their old spell labels show through the incoming page near touchdown.
OVERLAY_LIFT = 0.04
FIXED_OVERLAY_LIFT = 0.0
# Keep a paper occluder between old and new spell surfaces at touchdown.
# The unchanged turning spell lift .04 remains outside both paper faces.
PAPER_HALF_THICKNESS = 0.02
OUTLINER_WIDTH = 320
# Match the vertical camera reduction to keep glyphs and icons at their
# preceding 115x115 preview size; only the book and gaps become shorter.
OUTLINER_HEIGHT = 292
ICON_TOP = 40
ICON_BOTTOM = ICON_TOP + 128
TEXT_TOP = ICON_BOTTOM + 8
TEXT_WIDTH = 248
TEXT_LEFT = (OUTLINER_WIDTH-TEXT_WIDTH)//2
# Native book rays use world X relative to their origin. These ranges come from
# the fixed-leaf UV positions at icon x72..248: native 128px icon +24px per side.
# Rendering remains wider, so long labels can extend beyond the active area.
CAST_X_BOUNDS = [(-3.944406,-2.519531),(-2.183422,-0.752115),
                 (0.754845,2.171325),(2.510779,3.940645)]
# 6832d0 normalizes (0,3,-7) through 4737e0 before applying distance 17.
# eye = book centre + (0,-1,0) - 17*normalize(0,3,-7).
# A homothety about this eye keeps every control pixel in place while putting
# its real native triangles in front of the expanded/skinned spell overlays.
BOOK_CAMERA_EYE = (0.0,-1.0-51.0/math.sqrt(58.0),119.0/math.sqrt(58.0))
BUTTON_DEPTH_FRACTION = 0.025
# Stable open-leaf geometry for the twelve vanilla-style icon presets.
SPELL_TOOLTIP_PARTS = [10,26,11,27,12,28,7,35,8,36,9,37]

def xml_bytes(node):
    return b'<?xml version="1.0" encoding="UTF-8"?>\r\n' + ET.tostring(node, encoding='utf-8')

def resources(game_root, include_text_templates=True):
    GAME=Path(game_root)
    with zipfile.ZipFile(GAME/'data/data.pak') as z:
        desc = ET.fromstring(z.read('UI/SpellBook/SpellBook.(SpellBookDesc).xdb'))
        model = ET.fromstring(z.read(MODEL_DIR+'SpellBook.xdb'))
        geom = ET.fromstring(z.read(MODEL_DIR+'SpellBook-geom.xdb'))
        original = z.read('bin/Geometries/'+GEOM_UID)
    records = decode(original)
    assert encode(records) == original
    mesh_list = meshes(records)
    groups = [g for m in mesh_list.value if m.tag == 1 for g in m.value if g.tag == 1]
    assert len(groups) == 26
    material_items = list(model.find('Materials'))
    for part in (15,17):
        groups[part].value = project_forward(groups[part], BOOK_CAMERA_EYE, BUTTON_DEPTH_FRACTION).value
    for buffer, original_parts in enumerate(([10,11,12,2,3,4],[5,1,6,7,8,9])):
        for index, part in enumerate(original_parts):
            lift = OVERLAY_LIFT if part in (1,2,3,4,5,6) else FIXED_OVERLAY_LIFT
            left, right = split_columns(lift_surface(groups[part], lift))
            left = widen_label_uv(left, OUTLINER_WIDTH, OUTLINER_HEIGHT,
                                  ICON_BOTTOM, TEXT_TOP, TEXT_WIDTH,
                                  horizontal_scale=COLUMN_U_SCALE, column=0)
            right = widen_label_uv(right, OUTLINER_WIDTH, OUTLINER_HEIGHT,
                                   ICON_BOTTOM, TEXT_TOP, TEXT_WIDTH,
                                   horizontal_scale=COLUMN_U_SCALE, column=1)
            groups[part].value = left.value
            mesh_list.value.append(Record(1,[Record(2,struct.pack('<I',1)),right]))
            ET.SubElement(geom.find('MaterialQuantities'),'Item').text = '1'
            ET.SubElement(geom.find('MeshNames'),'Item').text = f'Grid12_{buffer}_{index}'
            model.find('Materials').append(copy.deepcopy(material_items[part]))
    # Share the subdivided spell triangles with the paper underneath them.
    all_groups = [g for m in mesh_list.value if m.tag == 1 for g in m.value if g.tag == 1]
    paper, _ = conform_paper(groups[0], [all_groups[i] for i in
        (1,2,3,4,5,6,29,30,31,32,33,34)], PAPER_HALF_THICKNESS)
    groups[0].value = paper.value
    mesh_list.child(2).value = struct.pack('<I',21)
    geom.find('NumMeshes').text = '21'
    geom.find('uid').text = NEW_UID
    model.find('Geometry').set('href', 'SpellBookProbe-geom.xdb#xpointer(/Geometry)')
    desc.find('Model').set('href', '/'+MODEL_DIR+'SpellBookProbe.xdb#xpointer(/Model)')
    for tag, parts in (('PartSpellsFirstPage',FRONT_PARTS),('PartSpellsSecondPage',BACK_PARTS)):
        desc.find(tag).clear()
        for part in parts: ET.SubElement(desc.find(tag),'Item').text = str(part)
    # The narrower vertical canvas compensates the lower book height.
    desc.find('OutlinerSize/x').text = str(OUTLINER_WIDTH)
    desc.find('OutlinerSize/y').text = str(OUTLINER_HEIGHT)
    desc.find('SpellIcon/x1').text = str(OUTLINER_WIDTH//2 - 64)
    desc.find('SpellIcon/x2').text = str(OUTLINER_WIDTH//2 + 64)
    desc.find('SpellIcon/y1').text = str(ICON_TOP)
    desc.find('SpellIcon/y2').text = str(ICON_BOTTOM)
    desc.find('SpellTextPosition/x').text = str(TEXT_LEFT)
    desc.find('SpellTextPosition/y').text = str(TEXT_TOP)
    mesh = encode(records)
    assert encode(decode(mesh)) == mesh
    payload = {
        'UI/SpellBook/SpellBook.(SpellBookDesc).xdb': xml_bytes(desc),
        MODEL_DIR+'SpellBookProbe.xdb': xml_bytes(model),
        MODEL_DIR+'SpellBookProbe-geom.xdb': xml_bytes(geom),
        'bin/Geometries/'+NEW_UID: mesh,
    }
    # Keep the native 26fx templates. Native word wrapping is constrained below.
    for filename in (('SpellInBookCanCast.txt','SpellInBookCanNotCast.txt') if include_text_templates else ()):
        name = 'UI/SpellBook/'+filename
        template=None
        for archive in ('texts.pak','universe_mod_texts_ru.pak'):
            if not (GAME/'data'/archive).is_file():
                continue
            with zipfile.ZipFile(GAME/'data'/archive) as z:
                if name in z.namelist():
                    template = z.read(name).decode('utf-16')
        if template is None:
            raise ValueError('Spellbook text template missing: '+name)
        payload[name] = template.encode('utf-16')
    return payload

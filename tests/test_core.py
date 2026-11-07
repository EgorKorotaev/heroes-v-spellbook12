import hashlib
import json
from pathlib import Path
import sys
import struct
from collections import Counter
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from spellbook12.native import build_native, validate_executable
from spellbook12.geometry import Record, encode, decode, conform_paper, positions, array
from spellbook12.build import build, zip_entries, RESOURCE_DATE


class NativeContractTests(unittest.TestCase):
    def setUp(self):
        self.approved=json.loads((ROOT/'tests/fixtures/approved-native.json').read_text())

    def test_generated_callbacks_match_approved_working_build(self):
        manifest,code=build_native(None,spell_anchors=self.approved['spell_tooltip_anchors'])
        self.assertEqual(json.loads(json.dumps(manifest)),self.approved)
        self.assertEqual(len(code),1280)
        self.assertEqual(hashlib.sha256(code).hexdigest(),'548ea0a99371d7da51dff0e8e8ca240f5ef3c901ce631a0a66e2b3cd49d8fb92')

    def test_rel32_relocations_target_the_declared_engine_functions(self):
        import struct
        manifest,code=build_native(None,spell_anchors=self.approved['spell_tooltip_anchors'])
        base=0x11da000
        for relocation in manifest['relocations']:
            at=relocation['offset']
            self.assertIn(code[at],[0xe8,0xe9])
            self.assertEqual(base+at+5+struct.unpack_from('<i',code,at+1)[0],relocation['target'])

    def test_incomplete_tooltip_table_is_rejected(self):
        with self.assertRaises(ValueError):build_native(None,spell_anchors=self.approved['spell_tooltip_anchors'][:6])

    def test_unsupported_executable_is_rejected_before_parsing(self):
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            validate_executable(b'not a game executable',self.approved)


class PackageTests(unittest.TestCase):
    def test_resource_zip_is_reproducible_and_order_independent(self):
        with tempfile.TemporaryDirectory()as temporary:
            a=Path(temporary)/'a.pak';b=Path(temporary)/'b.pak'
            zip_entries(a,{'z.bin':b'xyz','a.txt':b'abc'},RESOURCE_DATE)
            zip_entries(b,{'a.txt':b'abc','z.bin':b'xyz'},RESOURCE_DATE)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with zipfile.ZipFile(a)as archive:
                self.assertIsNone(archive.testzip())
                self.assertTrue(all(info.date_time==RESOURCE_DATE for info in archive.infolist()))

    def test_unknown_executable_does_not_create_any_build_output(self):
        with tempfile.TemporaryDirectory()as temporary:
            game=Path(temporary)/'game';(game/'bin').mkdir(parents=True)
            (game/'bin/H5_Game.exe').write_bytes(b'unsupported')
            output=Path(temporary)/'output'
            with self.assertRaisesRegex(ValueError,'SHA-256'):build(game,'universe',output)
            self.assertFalse(output.exists())

    def test_builder_refuses_to_write_inside_the_game(self):
        with tempfile.TemporaryDirectory()as temporary:
            game=Path(temporary)/'game'
            with self.assertRaisesRegex(ValueError,'outside'):build(game,'universe',game/'dist')
            self.assertFalse(game.exists())


class GeometryTests(unittest.TestCase):
    def sheet(self,ys,zs,offset=0):
        pp=[];attrs=[];skin=[];triangles=[]
        for side in (-1,1):
            base=len(pp)
            for y in ys:
                for z in zs:
                    pp.append((side*offset,y,z))
                    attrs.append(struct.pack('<2h',round(z*2048),round(y*2048))+b'\x80'*16)
                    w=.2+.6*y;q=round(w*255)
                    skin.append(struct.pack('<4f',w,1-w,0,0)+bytes((q,255-q,0,0,0,1,0,0)))
            for row in range(len(ys)-1):
                for col in range(len(zs)-1):
                    a=base+row*len(zs)+col;b=a+len(zs);c=b+1;d=a+1
                    for tri in [(a,b,c),(a,c,d)]:triangles.append(tri if side>0 else tri[::-1])
        count=len(pp)
        def field(tag,n,data):return Record(tag,[Record(1,struct.pack('<I',n)),Record(2,data)])
        sequential=struct.pack('<'+'H'*count,*range(count))
        return Record(1,[field(2,count,b''.join(struct.pack('<3f',*p)for p in pp)),
            field(3,count,b''.join(attrs)),field(4,count,b''.join(skin)),
            field(5,count,sequential),field(6,count,sequential),
            field(7,len(triangles),b''.join(struct.pack('<3H',*t)for t in triangles)),
            Record(9,struct.pack('<I',len(triangles)))])

    def conformed(self):
        paper=self.sheet([0,1],[0,.25,.75,1])
        spells=self.sheet([0,.4,.6,1],[.25,.5,.75],offset=.04)
        return paper,spells,conform_paper(paper,[spells],.02)

    def test_conformed_paper_retains_paper_uv_and_exact_spell_skin(self):
        paper,spells,(result,stats)=self.conformed()
        original=self.sheet([0,1],[0,.25,.75,1])
        self.assertEqual(encode([paper]),encode([original]))
        pp=positions(result);attrs=array(result,3);skin=array(result,4)
        spell_pp=positions(spells);spell_skin=array(spells,4)
        for i,p in enumerate(spell_pp):
            expected=(1 if p[0]>0 else -1)*.02
            matches=[j for j,q in enumerate(pp)if abs(q[0]-expected)<1e-7 and q[1:]==p[1:]]
            self.assertTrue(matches)
            self.assertTrue(any(skin[j*24:(j+1)*24]==spell_skin[i*24:(i+1)*24]for j in matches))
        for i,p in enumerate(pp):
            self.assertEqual(struct.unpack_from('<2h',attrs,i*20),(round(p[2]*2048),round(p[1]*2048)))
        self.assertGreater(stats['triangles'],12)

    def test_new_paper_edges_join_both_margins_without_t_junctions(self):
        _,_,(result,_)=self.conformed();pp=positions(result)
        remap=[v[0]for v in struct.iter_unpack('<H',array(result,5))];edges=Counter()
        for indexes in struct.iter_unpack('<3H',array(result,7)):
            tri=[pp[remap[i]]for i in indexes]
            for a,b in zip(tri,tri[1:]+tri[:1]):
                if a[2]==b[2] and a[2]in(.25,.75) and a[1]!=b[1]:
                    edge=tuple(sorted(tuple(round(x,7)for x in p)for p in(a,b)));edges[edge]+=1
        self.assertTrue(edges)
        self.assertTrue(all(count==2 for count in edges.values()),edges)

    def test_conformed_paper_rejects_missing_spells_or_excess_thickness(self):
        paper=self.sheet([0,1],[0,.25,.75,1])
        with self.assertRaises(ValueError):conform_paper(paper,[],.02)
        with self.assertRaises(ValueError):conform_paper(paper,[paper],.04)

    def test_records_preserve_nested_and_long_payloads(self):
        records=[Record(1,[Record(7,b'a'*300),Record(8,b'abc')])]
        encoded=encode(records)
        self.assertEqual(encode(decode(encoded)),encoded)

    def test_truncated_record_is_rejected(self):
        with self.assertRaises(ValueError):decode(bytes([7,20])+b'x')


if __name__=='__main__':unittest.main()

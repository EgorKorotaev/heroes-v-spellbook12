"""Build a portable player package from a locally installed, supported game."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from . import __version__
from .resources import resources
from .native import UNIVERSE_SHA256, build_native, validate_executable
from .h55 import EXES, build_h55_profile

ROOT=Path(__file__).resolve().parents[2]
# Fixed ZIP metadata makes the package reproducible. The high resource date
# gives the authored book entries priority in Heroes V's resource overlay.
RESOURCE_DATE=(2107,12,31,23,59,58)
FILE_DATE=(2026,11,7,0,0,0)
LABELS={'universe':'Universe','h55':'H55-RC19k'}
ENGINES={'universe':'H5_Game.exe','h55':'MMH55_64.exe'}
APP_FILES=['Spellbook12.psm1','Launch.ps1','Launch.cmd','Uninstall.ps1','Uninstall.cmd']
DOC_FILES=['README.txt','README.en.txt','LICENSE.txt','NOTICES.txt','CHANGELOG.txt','VALIDATION.txt']


def sha(data):return hashlib.sha256(data).hexdigest()


def json_bytes(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def script_bytes(path):
    text=path.read_text(encoding='utf-8-sig').replace('\r\n','\n').replace('\r','\n')
    if path.suffix in ['.ps1','.psm1']:
        return text.replace('\n','\r\n').encode('utf-8-sig')
    if path.suffix=='.cmd':return text.replace('\n','\r\n').encode('ascii')
    return text.encode('utf-8')


def zip_entries(path,entries,date):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9)as archive:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(name,date)
            info.compress_type=zipfile.ZIP_DEFLATED
            info.create_system=3
            info.external_attr=0o100644<<16
            archive.writestr(info,data,compresslevel=9)


def build(game_root,edition,output):
    game=Path(game_root).resolve()
    output=Path(output).resolve()
    if output==game or game in output.parents:
        raise ValueError('Build output must be outside the installed game')
    exe=game/'bin'/ENGINES[edition]
    source=exe.read_bytes()
    expected=UNIVERSE_SHA256 if edition=='universe'else EXES[ENGINES[edition]]
    if sha(source)!=expected:raise ValueError('Unsupported game executable SHA-256: '+sha(source))
    payload=resources(game,include_text_templates=edition=='universe')
    manifest,stub=build_native(payload)
    if edition=='h55':manifest,stub=build_h55_profile(source,manifest,stub)
    sites=validate_executable(source,manifest)
    name=f'Spellbook12-{__version__}-{LABELS[edition]}'
    output.mkdir(parents=True,exist_ok=True)
    target=output/name
    archive=output/(name+'.zip')
    if target.exists()or archive.exists():raise FileExistsError('Build output already exists: '+name)
    with tempfile.TemporaryDirectory(prefix='.spellbook12-build-',dir=output)as temporary:
        stage=Path(temporary)/name
        app=stage/'payload/Spellbook12'
        app.mkdir(parents=True)
        (stage/'resources').mkdir()
        zip_entries(stage/'resources/Spellbook12.pak',payload,RESOURCE_DATE)
        (app/'runtime-patch.json').write_bytes(json_bytes(manifest))
        (app/'callbacks.bin').write_bytes(stub)
        for filename in APP_FILES:(app/filename).write_bytes(script_bytes(ROOT/'windows'/filename))
        for filename in ['Install.ps1','Install.cmd']:(stage/filename).write_bytes(script_bytes(ROOT/'windows'/filename))
        for filename in DOC_FILES:(stage/filename).write_bytes(script_bytes(ROOT/filename))
        files=[]
        for path in sorted(app.iterdir()):
            files.append({'source':path.relative_to(stage).as_posix(),
                'destination':'Spellbook12/'+path.name,'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size})
        resource=stage/'resources/Spellbook12.pak'
        files.append({'source':'resources/Spellbook12.pak','destination':'data/Spellbook12.pak',
            'sha256':sha(resource.read_bytes()),'bytes':resource.stat().st_size})
        release={'schema':1,'package_id':'heroes-v-spellbook12','version':__version__,
            'edition':edition,'engine':{'path':'bin/'+ENGINES[edition],'sha256':manifest['source_sha256']},
            'files':files,'runtime_only':True,'exe_written':False,
            'verified_native_instruction_sites':sites,'slots_per_spread':12,
            'layout':{'columns_per_leaf':2,'rows_per_leaf':3,'book_width':1.25,'book_height':1.05},
            'resource_members_sha256':{n:sha(data)for n,data in sorted(payload.items())},
            'native_stub_sha256':sha(stub),'native_manifest_sha256':sha(json_bytes(manifest)),
            'network_play':'not_tested','lobby_launch':'not_tested'}
        (stage/'release.json').write_bytes(json_bytes(release))
        all_files={name+'/'+p.relative_to(stage).as_posix():p.read_bytes()for p in sorted(stage.rglob('*'))if p.is_file()}
        stage_zip=Path(temporary)/(name+'.zip')
        zip_entries(stage_zip,all_files,FILE_DATE)
        with zipfile.ZipFile(stage_zip)as check:
            if check.testzip()is not None:raise ValueError('Release archive integrity check failed')
            for entry,data in all_files.items():
                if check.read(entry)!=data:raise ValueError('Release archive mismatch: '+entry)
        if exe.read_bytes()!=source:raise ValueError('Source EXE changed during the build')
        shutil.move(str(stage),target)
        shutil.move(str(stage_zip),archive)
    return {'status':'built','edition':edition,'folder':str(target),'archive':str(archive),
        'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,
        'native_sites':sites,'source_exe_unmodified':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root',type=Path,required=True)
    parser.add_argument('--edition',choices=sorted(LABELS),required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args()
    print(json.dumps(build(args.game_root,args.edition,args.output),ensure_ascii=False))


if __name__=='__main__':main()

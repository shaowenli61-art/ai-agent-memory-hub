"""Build the primary deployable source package, excluding all user state."""
import argparse
import json
import shutil
import hashlib
import zipfile
from pathlib import Path
try:
    from scripts.update_local_release import allowed,verify_package
except ImportError:
    from update_local_release import allowed,verify_package

def build(output,root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve();output=Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new output directory; never overwrite an existing installation')
    output.mkdir(parents=True)
    rows=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():continue
        name=path.relative_to(root).as_posix()
        if not allowed(name):continue
        destination=output/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination)
        rows.append(dict(path=name,sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
    import tomllib
    project=root/'pyproject.toml'
    version=tomllib.loads(project.read_text(encoding='utf-8'))['project']['version'] if project.exists() else '0.2.1'
    manifest=dict(version=version,kind='real-local-source-deployment',python='3.11+',includes_private_data=False,files=rows)
    (output/'release-files.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    verify_package(output)
    archive=shutil.make_archive(str(output),'zip',output)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('Archive CRC verification failed')
    return dict(ok=True,archive=archive,files=len(rows)+1,sha256=hashlib.sha256(Path(archive).read_bytes()).hexdigest())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    print(json.dumps(build(args.output),ensure_ascii=False,indent=2))

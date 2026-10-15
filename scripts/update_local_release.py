"""Verified source-only updater; preserve all local settings and Vault state."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath

SOURCE_DIRS={'memory_hub','scripts','skills','protocols','workbench','docs','tests'}
ROOT_FILES={'README.md','README.zh-CN.md','INSTALL.md','AGENTS.md','LICENSE','SECURITY.md','.gitignore','pyproject.toml','requirements-semantic.txt','launch.py','stop.py','Start Workbench.cmd','Stop Workbench.cmd','Start Workbench.command'}
EXCLUDE={'__pycache__','bin','obj','publish','data','.git','.memory-hub','output','demo-data','local-data','personal-vault'}
SUFFIXES={'.py','.md','.js','.css','.html','.cs','.xaml','.csproj','.manifest','.json','.svg','.png','.ps1','.txt','.toml','.cmd','.command'}

def allowed(name):
    path=PurePosixPath(name)
    return bool(name and '\\' not in name and not path.is_absolute() and not any(p in ('..','.') for p in path.parts)
        and not any(p in EXCLUDE for p in path.parts)
        and (name in ROOT_FILES or (path.parts[0] in SOURCE_DIRS and path.suffix in SUFFIXES)))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify_package(package):
    package=Path(package).resolve()
    manifest=json.loads((package/'release-files.json').read_text(encoding='utf-8'))
    names=set()
    for row in manifest['files']:
        name=row['path'];path=(package/name).resolve()
        if not allowed(name) or name in names or not path.is_relative_to(package) or path.is_symlink() or not path.is_file():
            raise ValueError('Invalid release path')
        names.add(name)
        if digest(path)!=row['sha256']:
            raise ValueError('Release hash mismatch: '+name)
    if not names:
        raise ValueError('Empty release manifest')
    return manifest

def update(package,target):
    package=Path(package).resolve();target=Path(target).resolve()
    if package==target:
        raise ValueError('New package and installed source must be different directories')
    manifest=verify_package(package)
    if not target.is_dir() or (target/'20-Projects').exists() or (target/'.memory-hub').exists():
        raise ValueError('Target must be an existing code-only directory, not a Vault')
    settings_path=target/'local-settings.json'
    settings=json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
    if settings.get('mode')=='real':
        vault=Path(settings['vault']).resolve()
        if vault.is_relative_to(target):
            raise ValueError('Move the Vault outside the code directory before upgrading')
        if (vault/'.memory-hub/server.json').exists():
            raise ValueError('Stop the recorded workbench service before updating')
        backups=vault/'.memory-hub/backups/releases'
    else:
        backups=target.parent/'workbench-code-backups'
    backup=backups/(datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    saved=[];installed=[]
    # Validate every destination and save every old file before replacing anything.
    for row in manifest['files']:
        name=row['path'];destination=(target/name).resolve()
        if not destination.is_relative_to(target) or (target/name).is_symlink():
            raise ValueError('Installed source path escapes the code directory')
        if destination.is_file():
            old=backup/name;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,old)
            saved.append(dict(path=name,sha256=digest(old)))
    (backup/'release-files.json').write_text(json.dumps(dict(version='rollback-source',files=saved),ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        for row in manifest['files']:
            name=row['path'];destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(package/name,destination);installed.append(name)
        shutil.copy2(package/'release-files.json',target/'release-files.json')
    except Exception:
        for row in saved:
            shutil.copy2(backup/row['path'],target/row['path'])
        raise
    receipt=dict(ok=True,version=manifest.get('version'),backup=str(backup),installed=installed,
        retained=['local-settings.json','Vault configuration','knowledge sources','project pages','decision ledgers'],
        rollback_note='Overlay saved source files; newly added files are not automatically deleted')
    (backup/'update-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',type=Path,required=True);parser.add_argument('--target',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(update(args.package,args.target),ensure_ascii=False,indent=2))

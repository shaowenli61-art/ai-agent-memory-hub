"""Read-only startup checks shared by the launcher and Agent deployment."""
import importlib
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def inspect_startup(vault=None):
    problems=[];warnings=[]
    package=dict(integrity='source-checkout',authenticated=False)
    if sys.version_info<(3,11):problems.append('需要 Python 3.11+。')
    previous=sys.dont_write_bytecode;sys.dont_write_bytecode=True
    try:
        manifest=ROOT/'release-files.json'
        if manifest.exists():
            try:
                from scripts.update_local_release import verify_package
                verified=verify_package(ROOT)
                package.update(integrity='verified',version=verified.get('version'),files=len(verified['files']))
            except (OSError,ValueError,KeyError,TypeError) as error:
                package['integrity']='failed';problems.append('源码包校验失败：'+str(error))
        else:
            warnings.append('这是GitHub源码目录，没有发行校验清单；可以运行，但不能据此声称已验证发行包来源。')
        for name in ('launch.py','workbench/web/full/index.html','workbench/web/full/live.css',
                     'workbench/web/full/work-cycle.css','workbench/web/full/live.js','workbench/web/full/work-cycle.js'):
            if not (ROOT/name).is_file():problems.append('Missing startup file: '+name)
        entries={}
        if not problems:
            for name in ('scripts.demo_server','memory_hub.local_server'):
                try:
                    importlib.import_module(name);entries[name]='ok'
                except Exception as error:
                    entries[name]='failed';problems.append(name+'：'+type(error).__name__+': '+str(error))
        from memory_hub.workbench import doctor
        try:
            workbench=doctor(vault)
            problems.extend(workbench['problems'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            workbench=dict(ok=False);problems.append('本地配置体检失败：'+str(error))
    finally:
        sys.dont_write_bytecode=previous
    return dict(ok=not problems,mode='read-only',problems=problems,warnings=warnings,
                package=package,entrypoints=entries,workbench=workbench,
                global_rule_changes=False,model_downloads=False)

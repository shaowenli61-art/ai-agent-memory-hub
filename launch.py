"""First-run choices only; daily use opens the saved local workbench."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SETTINGS=ROOT/'local-settings.json'

def main():
    if sys.version_info<(3,11):
        raise SystemExit('需要 Python 3.11+。')
    from memory_hub.workbench import configure,doctor
    from memory_hub.local_server import serve
    report=doctor()
    if not report['ok']:
        raise SystemExit('\n'.join(report['problems']))
    if SETTINGS.exists():
        settings=json.loads(SETTINGS.read_text(encoding='utf-8'))
    else:
        print('1 接入我的真实工作（默认）\n2 使用独立虚构样例体验')
        mode=input('选择 [1/2]：').strip() or '1'
        if mode not in ('1','2'):
            raise SystemExit('请选择 1 或 2。')
        if mode=='2':
            settings=dict(mode='demo')
        else:
            vault=input('记忆库目录（留空在包旁创建 personal-vault）：').strip().strip('"')
            vault=Path(vault).expanduser().resolve() if vault else ROOT.parent/'personal-vault'
            job=input('已有岗位知识库目录（可留空）：').strip().strip('"')
            personal=input('已有个人知识库目录（可留空）：').strip().strip('"')
            configure(vault,job=Path(job) if job else None,personal=Path(personal) if personal else None)
            settings=dict(mode='real',vault=str(vault),port=8896)
        SETTINGS.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    if settings['mode']=='demo':
        from scripts.demo_server import initialize,serve as demo_serve
        print('虚构样例，与真实记忆库隔离。http://127.0.0.1:8897/full/index.html',flush=True)
        import webbrowser
        config=initialize();webbrowser.open('http://127.0.0.1:8897/full/index.html')
        demo_serve(config,8897)
    else:
        serve(Path(settings['vault']),settings.get('port',8896))

if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError) as error:
        print('启动失败：'+str(error),file=sys.stderr)
        raise SystemExit(1)

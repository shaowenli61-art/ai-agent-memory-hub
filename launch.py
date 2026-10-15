"""Local launcher with a read-only check and non-interactive Agent options."""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
SETTINGS=ROOT/'local-settings.json'

def main(argv=None):
    parser=argparse.ArgumentParser(description='个人工作台启动器；Agent先运行 --check')
    parser.add_argument('--check',action='store_true',help='只读体检，不创建资料或修改规则')
    parser.add_argument('--mode',choices=('demo','real'),help='体验或真实工作；省略则读取已保存选择')
    for name in ('vault','job','personal'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--port',type=int)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args(argv)
    from memory_hub.preflight import inspect_startup
    report=inspect_startup(args.vault if args.check else None)
    if args.check:
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['ok'] else 1
    if not report['ok']:raise ValueError('\n'.join(report['problems'])+'\n请让Agent读取 INSTALL.md 排查。')
    prior=json.loads(SETTINGS.read_text(encoding='utf-8')) if SETTINGS.exists() else {}
    if not isinstance(prior,dict):raise ValueError('启动设置格式不正确；请让Agent检查 local-settings.json，不要删除个人资料。')
    mode=args.mode or prior.get('mode')
    if mode is None:
        print('1 接入我的真实工作（默认）\n2 使用独立虚构样例体验')
        choice=input('选择 [1/2]：').strip() or '1'
        if choice not in ('1','2'):raise ValueError('请选择 1 或 2。')
        mode='demo' if choice=='2' else 'real'
    if mode not in ('demo','real'):raise ValueError('启动设置中的 mode 必须是 demo 或 real。')
    settings=dict(prior,mode=mode)
    saved_port=prior.get('port') if prior.get('mode')==mode else None
    port=args.port if args.port is not None else int(saved_port or (8897 if mode=='demo' else 8896))
    if not 1<=port<=65535:raise ValueError('端口必须在1到65535之间。')
    settings['port']=port

    def remember():
        staging=SETTINGS.with_suffix('.json.tmp')
        staging.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
        staging.replace(SETTINGS)

    if mode=='demo':
        from scripts.demo_server import initialize,serve
        config=initialize()
        print('虚构样例，与真实记忆库隔离。',flush=True)
        serve(config,port,open_browser=not args.no_browser,on_started=remember)
    else:
        from memory_hub.workbench import configure
        from memory_hub.local_server import serve
        vault=args.vault or (Path(prior['vault']) if prior.get('mode')=='real' and prior.get('vault') else None)
        if vault is None:
            value=input('记忆库目录（留空在包旁创建 personal-vault）：').strip().strip('"')
            vault=Path(value) if value else ROOT.parent/'personal-vault'
            job=input('已有岗位知识库目录（可留空）：').strip().strip('"')
            personal=input('已有个人知识库目录（可留空）：').strip().strip('"')
            args.job=args.job or (Path(job) if job else None)
            args.personal=args.personal or (Path(personal) if personal else None)
        vault=vault.expanduser().resolve()
        configure(vault,job=args.job,personal=args.personal)
        settings['vault']=str(vault)
        serve(vault,port,not args.no_browser,on_started=remember)
    return 0

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,ImportError,EOFError) as error:
        print('启动失败：'+str(error)+'\n可先运行 python -B launch.py --check，或让Agent读取 INSTALL.md。',file=sys.stderr)
        raise SystemExit(1)

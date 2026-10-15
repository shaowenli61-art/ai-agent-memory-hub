from __future__ import annotations

import argparse
import json
from pathlib import Path

from memory_hub.deploy import apply_install_plan, build_install_plan, inspect_environment, verify_install
from memory_hub.workflow import close_task, write_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory-hub", description="Agent-deployable local memory hub")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="inspect the environment without making changes")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--home", type=Path)
    doctor.add_argument("--system", help=argparse.SUPPRESS)
    plan = commands.add_parser("plan", help="write a reviewable install plan without making changes")
    plan.add_argument("--vault", type=Path, required=True)
    plan.add_argument("--agent", action="append", default=[])
    plan.add_argument("--rule-scope", choices=("global", "project"), required=True)
    plan.add_argument("--project-root", type=Path)
    plan.add_argument("--workbench", choices=("none", "web", "desktop"), required=True)
    plan.add_argument("--growth-mode", choices=("enabled", "disabled"), required=True)
    plan.add_argument("--home", type=Path)
    plan.add_argument("--system", help=argparse.SUPPRESS)
    plan.add_argument("--output", type=Path, required=True)
    install = commands.add_parser("install", help="apply a saved plan after explicit confirmation")
    install.add_argument("--plan", type=Path, required=True)
    install.add_argument("--yes", action="store_true", help="confirm the reviewed plan")
    install.add_argument("--package-root", type=Path, help=argparse.SUPPRESS)
    close = commands.add_parser("close", help="record a task outcome and refresh the workbench snapshot")
    close.add_argument("--vault", type=Path, required=True)
    close.add_argument("--task", required=True)
    close.add_argument(
        "--status",
        choices=("active", "completed", "stage-complete", "waiting", "blocked", "handoff", "terminated"),
        required=True,
    )
    close.add_argument("--completed", required=True)
    close.add_argument("--next-action", required=True)
    close.add_argument("--evidence", action="append", default=[])
    close.add_argument("--agent", default="")
    close.add_argument("--collaborator", default="")
    close.add_argument('--project',default='',help='registered project name for a verified project receipt')
    close.add_argument('--remaining',default='未登记')
    close.add_argument('--risks',default='无')
    close.add_argument('--avoid-repeat',default='无')
    close.add_argument('--verification',default='',help='actual checks and results, never inferred from completion')
    verify = commands.add_parser("verify", help="verify a deployed memory hub")
    verify.add_argument("--vault", type=Path, required=True)
    snapshot = commands.add_parser("snapshot", help="rebuild the workbench snapshot")
    snapshot.add_argument("--vault", type=Path, required=True)
    setup=commands.add_parser('setup',help='configure real local sources without changing Agent rules')
    setup.add_argument('--vault',type=Path,required=True)
    for flag in ('job','personal','semantic-model','semantic-onnx','reranker'):
        setup.add_argument('--'+flag,type=Path)
    setup.add_argument('--owner')
    project=commands.add_parser('project',help='register an existing project directory without moving files')
    project.add_argument('--vault',type=Path,required=True)
    project.add_argument('--name',required=True)
    project.add_argument('--path',type=Path,required=True)
    project.add_argument('--goal',default='')
    project.add_argument('--next-action',default='先核对项目当前成果、阻塞与证据。')
    serve=commands.add_parser('serve',help='start the complete operating workbench on loopback')
    serve.add_argument('--vault',type=Path,required=True)
    serve.add_argument('--port',type=int,default=8896)
    serve.add_argument('--no-browser',action='store_true')
    stop=commands.add_parser('stop',help='stop only the recorded local workbench instance')
    stop.add_argument('--vault',type=Path,required=True)
    check=commands.add_parser('workbench-doctor',help='check FTS5 and configured sources without changing them')
    check.add_argument('--vault',type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        report = inspect_environment(home=args.home, system=args.system)
        from memory_hub.preflight import inspect_startup
        report['startup']=inspect_startup()
        report['ok']=report['startup']['ok']
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Platform: {report['platform']}")
            for name, state in report["agents"].items():
                label = "found" if state["installed"] else "not found"
                print(f"- {name}: {label} ({state['rule_file']})")
            for name, state in report["prerequisites"].items():
                label = "found" if state["installed"] else "not found"
                print(f"- {name}: {label}")
            for problem in report['startup']['problems']:print('- '+problem)
        return 0 if report['ok'] else 1
    if args.command == "plan":
        environment = inspect_environment(home=args.home, system=args.system)
        plan = build_install_plan(
            environment=environment,
            vault=args.vault,
            agents=args.agent,
            rule_scope=args.rule_scope,
            project_root=args.project_root,
            workbench=args.workbench,
            growth_mode=args.growth_mode,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(args.output)
        return 0
    if args.command == "install":
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        package_root = args.package_root or Path(__file__).resolve().parents[1]
        receipt = apply_install_plan(plan, package_root=package_root, confirmed=args.yes)
        receipt_path = Path(plan["vault"]) / ".memory-hub" / "install-receipt.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    if args.command == "close":
        receipt = close_task(
            vault=args.vault.resolve(),
            task=args.task,
            status=args.status,
            completed=args.completed,
            next_action=args.next_action,
            evidence=args.evidence,
            agent=args.agent,
            collaborator=args.collaborator,
            project=args.project,remaining=args.remaining,risks=args.risks,avoid_repeat=args.avoid_repeat,verification=args.verification,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    if args.command == "verify":
        report = verify_install(args.vault)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if args.command == "snapshot":
        path = write_snapshot(args.vault.resolve())
        print(path)
        return 0
    if args.command=='setup':
        from memory_hub.workbench import configure,doctor,refresh_snapshot
        configure(args.vault,job=args.job,personal=args.personal,owner=args.owner,semantic_model=args.semantic_model,semantic_onnx=args.semantic_onnx,reranker=args.reranker)
        refresh_snapshot(args.vault)
        print(json.dumps(doctor(args.vault),ensure_ascii=False,indent=2))
        return 0
    if args.command=='project':
        from memory_hub.workbench import register_project
        print(json.dumps(register_project(args.vault,args.name,args.path,args.goal,args.next_action),ensure_ascii=False,indent=2))
        return 0
    if args.command=='serve':
        from memory_hub.local_server import serve
        serve(args.vault,args.port,not args.no_browser)
        return 0
    if args.command=='stop':
        from memory_hub.local_server import stop
        print(json.dumps(stop(args.vault),ensure_ascii=False,indent=2))
        return 0
    if args.command=='workbench-doctor':
        from memory_hub.preflight import inspect_startup
        report=inspect_startup(args.vault)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['ok'] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

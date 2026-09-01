from __future__ import annotations

import platform
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from memory_hub.workflow import write_snapshot


AGENT_RULES = {
    "claude": (".claude/CLAUDE.md", "claude"),
    "codex": (".codex/AGENTS.md", "codex"),
    "gemini": (".gemini/GEMINI.md", "gemini"),
    "workbuddy": (".workbuddy/USER.md", "workbuddy"),
    "qoder": (".qoder/AGENTS.md", "qodercli"),
    "qoderwork": (".qoderwork/AGENTS.md", "qodercli"),
}
PROJECT_RULES = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "workbuddy": "AGENTS.md",
    "qoder": "AGENTS.md",
    "qoderwork": "AGENTS.md",
}

RULES_START = "<!-- AI_MEMORY_HUB_RULES_V1:START -->"
RULES_END = "<!-- AI_MEMORY_HUB_RULES_V1:END -->"
RULES_PATTERN = re.compile(
    re.escape(RULES_START) + r".*?" + re.escape(RULES_END),
    re.S,
)


def _platform_name(system: str) -> str:
    value = system.strip().lower()
    if value == "darwin":
        return "macos"
    return value


def inspect_environment(*, home: Path | None = None, system: str | None = None) -> dict:
    user_home = (home or Path.home()).expanduser().resolve()
    platform_name = _platform_name(system or platform.system())
    agents: dict[str, dict[str, object]] = {}
    for name, (relative_rule, command) in AGENT_RULES.items():
        rule_file = user_home / Path(relative_rule)
        agents[name] = {
            "installed": rule_file.exists() or shutil.which(command) is not None,
            "rule_file": str(rule_file),
            "rule_file_exists": rule_file.exists(),
        }
    if platform_name == "windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", user_home / "AppData" / "Local"))
        program_files = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
        obsidian_candidates = [
            local_app_data / "Obsidian" / "Obsidian.exe",
            local_app_data / "Programs" / "Obsidian" / "Obsidian.exe",
            program_files / "Obsidian" / "Obsidian.exe",
        ]
        webview_candidates = [
            program_files_x86 / "Microsoft/EdgeWebView/Application"
        ]
        browser_candidates = [
            program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
            program_files / "Google/Chrome/Application/chrome.exe",
            local_app_data / "Google/Chrome/Application/chrome.exe",
        ]
    elif platform_name == "macos":
        obsidian_candidates = [Path("/Applications/Obsidian.app"), user_home / "Applications/Obsidian.app"]
        webview_candidates = []
        browser_candidates = [Path("/Applications/Safari.app"), Path("/Applications/Google Chrome.app")]
    else:
        obsidian_candidates = []
        webview_candidates = []
        browser_candidates = []
    browser_commands = ("msedge", "chrome", "google-chrome", "chromium", "safari")
    prerequisites = {
        "python": {
            "installed": True,
            "version": platform.python_version(),
            "supported": sys.version_info >= (3, 11),
        },
        "obsidian": {
            "installed": any(path.exists() for path in obsidian_candidates),
            "required_for_core": False,
        },
        "browser": {
            "installed": any(shutil.which(command) is not None for command in browser_commands)
            or any(path.exists() for path in browser_candidates),
            "required_for_web": True,
        },
        "dotnet": {
            "installed": shutil.which("dotnet") is not None,
            "required_for_desktop_build": platform_name == "windows",
        },
        "webview2": {
            "installed": any(path.exists() for path in webview_candidates),
            "required_for_desktop": platform_name == "windows",
        },
    }
    return {
        "platform": platform_name,
        "home": str(user_home),
        "agents": agents,
        "prerequisites": prerequisites,
        "workbench_options": {
            "none": True,
            "web": True,
            "desktop": platform_name == "windows",
        },
    }


def build_install_plan(
    *,
    environment: dict,
    vault: Path,
    agents: list[str],
    rule_scope: str,
    workbench: str,
    project_root: Path | None = None,
    growth_mode: str = "enabled",
) -> dict:
    platform_name = str(environment["platform"])
    if workbench == "desktop" and platform_name != "windows":
        raise ValueError("Desktop Workbench is available for Windows 10/11 only")
    unknown = sorted(set(agents) - set(AGENT_RULES))
    if unknown:
        raise ValueError(f"unsupported agents: {', '.join(unknown)}")
    if rule_scope not in {"global", "project"}:
        raise ValueError("rule_scope must be global or project")
    if growth_mode not in {"enabled", "disabled"}:
        raise ValueError("growth_mode must be enabled or disabled")
    if rule_scope == "project":
        if project_root is None:
            raise ValueError("project_root is required for project rule scope")
        project = project_root.expanduser().resolve()
        rule_targets = {name: str(project / PROJECT_RULES[name]) for name in agents}
    else:
        rule_targets = {name: environment["agents"][name]["rule_file"] for name in agents}
    return {
        "schema_version": 1,
        "platform": platform_name,
        "vault": str(vault.expanduser().resolve()),
        "agents": agents,
        "rule_targets": rule_targets,
        "rule_scope": rule_scope,
        "workbench": workbench,
        "growth_mode": growth_mode,
        "detected_prerequisites": environment.get("prerequisites", {}),
    }


def _initialize_vault(vault: Path) -> None:
    directories = (
        "00-Inbox",
        "10-Daily",
        "20-Projects",
        "40-AI-Transformation",
        "50-Agent-Workflows/00-Dashboard",
        "90-Reviews",
    )
    for relative in directories:
        (vault / relative).mkdir(parents=True, exist_ok=True)
    readme = vault / "README.md"
    if not readme.exists():
        readme.write_text(
            "# AI Agent Memory Hub\n\n"
            "This vault stores your own project facts, decisions, worklogs, and agent handoffs.\n",
            encoding="utf-8",
        )
    starter_files = {
        vault / "20-Projects" / "项目索引.md": (
            "# 项目索引\n\n"
            "> 只登记已经存在或已明确立项的项目。\n\n"
            "| 项目 | 状态 | 当前事实 | 下一步 | 证据 |\n"
            "|---|---|---|---|---|\n"
        ),
        vault / "50-Agent-Workflows" / "00-Dashboard" / "当前任务.md": (
            "# 当前任务\n\n"
            "- 当前主线：无\n"
            "- 真实状态：等待登记\n"
            "- 下一步：由用户与 Agent 确认首个任务\n"
            "- 证据：无\n"
        ),
        vault / "50-Agent-Workflows" / "00-Dashboard" / "多Agent协同看板.md": (
            "# 多 Agent 协同看板\n\n"
            "## 文件占用\n\n无。\n\n"
            "## 待交接\n\n无。\n"
        ),
    }
    for path, content in starter_files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def _render_rule_block(vault: Path, package_root: Path, protocol: str | None) -> str:
    base = (
        f"{RULES_START}\n"
        "## AI Agent Memory Hub\n\n"
        f"- Shared memory vault: `{vault}`\n"
        f"- Memory Hub repository: `{package_root}`\n"
        "- Before project work, read `README.md`, `20-Projects/项目索引.md`, and "
        "`50-Agent-Workflows/00-Dashboard/当前任务.md` from the Vault.\n"
        "- Write only verified facts, decisions, evidence, and next actions.\n"
        "- Never store passwords, API keys, cookies, or full connection strings.\n"
        f"- At task close, run from `{package_root}`: `python -m memory_hub close --vault \"{vault}\" ...`.\n"
    )
    if protocol:
        base += f"\n{protocol.strip()}\n"
    return base + RULES_END


def apply_install_plan(plan: dict, *, package_root: Path, confirmed: bool) -> dict:
    if not confirmed:
        raise PermissionError("install plan must be confirmed before changes are applied")
    vault = Path(plan["vault"])
    _initialize_vault(vault)
    protocol_path = package_root / "protocols" / "growth-ai-collaboration-v3.2.1.md"
    protocol = (
        protocol_path.read_text(encoding="utf-8")
        if plan.get("growth_mode", "enabled") == "enabled"
        else None
    )
    block = _render_rule_block(vault, package_root.resolve(), protocol)
    backup_root = vault / ".memory-hub" / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backups: list[str] = []
    updated: list[str] = []
    for agent, raw_target in plan["rule_targets"].items():
        target = Path(raw_target)
        target.parent.mkdir(parents=True, exist_ok=True)
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        if RULES_PATTERN.search(old):
            new = RULES_PATTERN.sub(lambda _: block, old, count=1)
        else:
            new = old.rstrip() + ("\n\n" if old.strip() else "") + block + "\n"
        if new == old:
            continue
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = backup_root / f"{agent}-{stamp}-{target.name}"
            backup.write_text(old, encoding="utf-8")
            backups.append(str(backup))
        target.write_text(new, encoding="utf-8")
        updated.append(str(target))
    web_workbench = ""
    if plan["workbench"] in {"web", "desktop"}:
        web_source = package_root / "workbench" / "web"
        if not web_source.exists():
            raise FileNotFoundError(f"web workbench source not found: {web_source}")
        web_install = vault / ".memory-hub" / "workbench" / "web"
        shutil.copytree(web_source, web_install, dirs_exist_ok=True)
        data_dir = web_install / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        write_snapshot(vault)
        web_workbench = str(web_install)
    return {
        "status": "installed",
        "vault": str(vault),
        "updated_rule_files": updated,
        "managed_rule_files": list(plan["rule_targets"].values()),
        "backups": backups,
        "workbench": plan["workbench"],
        "web_workbench": web_workbench,
        "desktop_status": "pending-script" if plan["workbench"] == "desktop" else "not-requested",
    }


def verify_install(vault: Path) -> dict:
    root = vault.expanduser().resolve()
    receipt_path = root / ".memory-hub" / "install-receipt.json"
    problems: list[str] = []
    missing_rule_blocks: list[str] = []
    if not (root / "README.md").exists():
        problems.append("vault README is missing")
    if not (root / "20-Projects" / "项目索引.md").exists():
        problems.append("project index is missing")
    if not (root / "50-Agent-Workflows" / "00-Dashboard" / "当前任务.md").exists():
        problems.append("current-task dashboard is missing")
    if not receipt_path.exists():
        problems.append("install receipt is missing")
        receipt: dict = {}
    else:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for raw_target in receipt.get("managed_rule_files", receipt.get("updated_rule_files", [])):
        target = Path(raw_target)
        if not target.exists() or RULES_START not in target.read_text(encoding="utf-8"):
            missing_rule_blocks.append(str(target))
    workbench = receipt.get("workbench", "none")
    if workbench in {"web", "desktop"}:
        web_root = root / ".memory-hub" / "workbench" / "web"
        if not (web_root / "index.html").exists():
            problems.append("web workbench is missing")
        if not (web_root / "data" / "operations_snapshot.json").exists():
            problems.append("workbench snapshot is missing")
    if workbench == "desktop":
        desktop_receipt = root / ".memory-hub" / "desktop-install.json"
        if not desktop_receipt.exists():
            problems.append("Windows desktop workbench installation is not recorded")
        else:
            desktop = json.loads(desktop_receipt.read_text(encoding="utf-8"))
            if not Path(desktop.get("executable", "")).exists():
                problems.append("Windows desktop workbench executable is missing")
    return {
        "ok": not problems and not missing_rule_blocks,
        "vault": str(root),
        "problems": problems,
        "missing_rule_blocks": missing_rule_blocks,
        "workbench": workbench,
    }

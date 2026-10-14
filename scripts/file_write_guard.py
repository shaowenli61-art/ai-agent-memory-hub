from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "paths.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def default_snapshot_root() -> Path:
    config = load_config()
    return Path(config["memory_vault"]) / "50-Agent-Workflows" / "90-Logs" / "write-snapshots"


def safe_name(path: Path) -> str:
    raw = str(path.resolve())
    return re.sub(r"[^A-Za-z0-9_.-]+", "__", raw).strip("_")


def suspicious_deletion(old: str, new: str) -> bool:
    old_text = old.strip()
    new_text = new.strip()
    if not old_text:
        return False
    if not new_text:
        return True
    old_len = len(old_text)
    new_len = len(new_text)
    if old_len < 300:
        return False
    removed_ratio = 1 - (new_len / old_len)
    return removed_ratio >= 0.7


def snapshot_file(path: Path, actor: str, reason: str, snapshot_root: Path | None = None) -> Path | None:
    if not path.exists():
        return None
    root = snapshot_root or default_snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    snapshot = root / f"{stamp}-{safe_name(path)}.md"
    meta = snapshot.with_suffix(snapshot.suffix + ".json")
    text = path.read_text(encoding="utf-8")
    snapshot.write_text(text, encoding="utf-8")
    meta.write_text(
        json.dumps(
            {
                "target": str(path),
                "actor": actor,
                "reason": reason,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return snapshot


def safe_write_text(
    path: Path | str,
    content: str,
    actor: str,
    reason: str,
    snapshot_root: Path | str | None = None,
    allow_mass_deletion: bool = False,
) -> Path | None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    root = Path(snapshot_root) if snapshot_root else None
    snapshot = snapshot_file(target, actor, reason, root)
    if not allow_mass_deletion and suspicious_deletion(old, content):
        raise RuntimeError(f"write rejected: suspicious mass deletion for {target}")
    target.write_text(content, encoding="utf-8")
    return snapshot


def restore_snapshot(snapshot: Path | str, target: Path | str | None = None) -> Path:
    snapshot_path = Path(snapshot)
    meta_path = snapshot_path.with_suffix(snapshot_path.suffix + ".json")
    if target is None:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        target_path = Path(meta["target"])
    else:
        target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(snapshot_path.read_text(encoding="utf-8"), encoding="utf-8")
    return target_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="协同写入快照与回滚工具")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--path", required=True)
    snap.add_argument("--actor", default="Codex")
    snap.add_argument("--reason", default="manual snapshot")
    restore = sub.add_parser("restore")
    restore.add_argument("--snapshot", required=True)
    restore.add_argument("--target")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "snapshot":
        snapshot = snapshot_file(Path(args.path), args.actor, args.reason)
        print(snapshot or "")
        return 0
    restored = restore_snapshot(args.snapshot, args.target)
    print(restored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

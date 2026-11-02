"""Mechanical export/drift check for the one authored growth Module."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sync(source_root, target_root, *, apply=False):
    source = Path(source_root).resolve() / "memory_growth"
    target = Path(target_root).resolve() / "memory_growth"
    if not source.is_dir() or not (Path(target_root) / "pyproject.toml").is_file():
        raise ValueError("source Module and target product must exist")
    files = {p.name: p for p in source.glob("*.py") if p.is_file() and not p.is_symlink()}
    if not files or any(p.name not in files for p in target.glob("*.py")):
        raise ValueError("empty source or unexpected target Module files; never delete silently")
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}
    changed = [name for name, path in files.items() if not (target / name).is_file()
        or (target / name).read_bytes() != path.read_bytes()]
    manifest = {"schema_version": 1, "module": "memory_growth", "files": hashes}
    if apply:
        target.mkdir(parents=True, exist_ok=True)
        for name in changed:
            shutil.copy2(files[name], target / name)
        (target / "source-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": apply or not changed, "mode": "apply" if apply else "check", "changed": changed,
        "source_fingerprint": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "files": len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = sync(args.source_root, args.target_root, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

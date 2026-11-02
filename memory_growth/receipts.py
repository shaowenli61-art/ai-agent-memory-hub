"""Formal memory receipt contract and legacy normalization boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping


FORMAL_RECEIPT_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class LegacyReceiptView:
    receipt: dict[str, Any]
    raw_line_sha256: str
    normalized_view_sha256: str


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str
    project_status: str

    @property
    def scope(self) -> str:
        return f"project:{self.project_id}"


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _record_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_timezone(timestamp: str) -> None:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601 with a timezone") from exc
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")


def seal_formal_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return one canonical schema v3 receipt with a self-verifiable hash."""

    record = {key: value for key, value in payload.items() if key != "record_hash"}
    record["schema_version"] = FORMAL_RECEIPT_SCHEMA_VERSION
    required = ("receipt_id", "task_id", "project_id", "scope", "timestamp")
    missing = [name for name in required if not str(record.get(name, "")).strip()]
    if missing:
        raise ValueError(f"formal receipt fields incomplete: {', '.join(missing)}")
    project_id = str(record["project_id"]).strip()
    if str(record["scope"]).strip() != f"project:{project_id}":
        raise ValueError("formal receipt scope must match project_id")
    _require_timezone(str(record["timestamp"]).strip())
    return {**record, "record_hash": _record_hash(record)}


def verify_formal_receipt(receipt: Mapping[str, Any]) -> bool:
    """Verify the schema and deterministic record hash of a formal receipt."""

    if receipt.get("schema_version") != FORMAL_RECEIPT_SCHEMA_VERSION:
        return False
    claimed = str(receipt.get("record_hash", ""))
    payload = {key: value for key, value in receipt.items() if key != "record_hash"}
    try:
        _require_timezone(str(payload.get("timestamp", "")))
    except ValueError:
        return False
    return bool(claimed) and claimed == _record_hash(payload)


def require_valid_formal_receipt(receipt: Mapping[str, Any]) -> None:
    """Fail closed at every derived consumer; a false verifier is not success."""
    if type(receipt.get("schema_version")) is not int or not verify_formal_receipt(receipt):
        raise ValueError("formal receipt record_hash validation failed")
    seal_formal_receipt(receipt)  # Also require identity, scope and timezone.


def normalize_legacy_receipt_line(
    raw_line: str,
    *,
    project_id: str,
    assume_timezone: str,
) -> LegacyReceiptView:
    """Build a hashed compatibility view without changing the legacy source line."""

    if re.fullmatch(r"[+-](?:0\d|1\d|2[0-3]):[0-5]\d", assume_timezone) is None:
        raise ValueError("assume_timezone must be an explicit UTC offset")
    receipt = json.loads(raw_line)
    if not isinstance(receipt, dict):
        raise ValueError("legacy receipt line must contain a JSON object")
    timestamp = str(receipt.get("timestamp", "")).strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("legacy receipt timestamp must be ISO-8601") from exc
    if parsed.utcoffset() is None:
        timestamp = f"{timestamp}{assume_timezone}"
        parsed = datetime.fromisoformat(timestamp)
    timestamp = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )
    normalized = {
        **receipt,
        "project_id": project_id,
        "scope": f"project:{project_id}",
        "timestamp": timestamp,
    }
    return LegacyReceiptView(
        receipt=normalized,
        raw_line_sha256=hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
        normalized_view_sha256=_record_hash(normalized),
    )


def project_identity_from_text(text: str) -> ProjectIdentity:
    """Read the formal project identity from Obsidian frontmatter."""

    match = re.match(r"\A---\s*\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise ValueError("project frontmatter is required")

    def value(name: str) -> str:
        field = re.search(rf"(?m)^{re.escape(name)}\s*:\s*(.+?)\s*$", match.group("body"))
        return field.group(1).strip().strip('"\'') if field else ""

    project_id = value("project_id")
    project_status = value("project_status")
    if not project_id:
        raise ValueError("project_id is required in project frontmatter")
    if not project_status:
        raise ValueError("project_status is required in project frontmatter")
    return ProjectIdentity(project_id=project_id, project_status=project_status)

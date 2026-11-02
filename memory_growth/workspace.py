"""Growth projections for existing closure/work-cycle Adapters.

Formal receipts and user decisions stay authoritative. This Module only appends
traceable events and rebuildable projections; it never runs an Agent on reads.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re

from . import GrowthInput, project_admissions, review_task, __version__
from ._core import DEFAULT_RULES, normalize_growth_event
from ._core import build_review_prompt, evaluate_trigger
from .evaluation import preserve_evaluation_sections, project_evaluation_events, read_evaluation_events, record_event_file
from .receipts import require_valid_formal_receipt
from .reporting import affected_report_months, default_schema_start, render_report, summarize_month


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(content):
    return hashlib.sha256(content if isinstance(content, bytes) else content.encode()).hexdigest()


def _instant(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


class SourceContinuityError(ValueError):
    def __init__(self, source):
        self.source = source
        super().__init__('growth source is not an append-only continuation: ' + source)


def linked_feedback_records(receipts, rows):
    """Resolve primary feedback evidence; feedback never grants Policy authority."""
    by_receipt = {row.get('receipt_id'): row for row in receipts}
    linked = []
    for event in rows:
        if not isinstance(event, dict) or event.get('record_hash') != _sha(_json({k: v for k, v in event.items() if k != 'record_hash'})):
            raise ValueError('work-cycle feedback hash validation failed')
        if event.get('action') != 'review':
            continue
        ref = event.get('data', {}).get('delivery', {}).get('episode_ref', {})
        source = by_receipt.get(ref.get('receipt_id'))
        if source and source.get('schema_version') == 3 and source.get('record_hash') and source.get('task_id') == ref.get('task_id') and source.get('record_hash') == ref.get('record_hash'):
            require_valid_formal_receipt(source)
            linked.append((source, event))
    return linked


class GrowthWorkspace:
    def __init__(self, config, *, writer=None):
        self.config = dict(config)
        self.vault = Path(config["memory_hub_root"]).expanduser().resolve()
        self.mode = config.get("growth_mode", "legacy_unconfigured")
        if self.mode not in {"enabled", "disabled", "legacy_unconfigured"}:
            raise ValueError("invalid growth_mode")
        self.runtime = Path(config.get('growth_runtime_root') or self.vault.with_name(self.vault.name + '.growth-runtime')).expanduser().resolve()
        code_root = Path(__file__).resolve().parents[1]
        if self.mode == 'enabled' and (self.runtime.is_relative_to(self.vault) or self.runtime.is_relative_to(code_root)
                or self.vault.is_relative_to(self.runtime) or code_root.is_relative_to(self.runtime)):
            raise ValueError('growth runtime must be a dedicated directory outside the Vault and code repository')
        self.writer = writer

    def path(self, name):
        path = self.vault / name
        if not path.resolve().is_relative_to(self.vault):
            raise ValueError("growth path escapes the selected Vault")
        return path

    def _write(self, path, content):
        if self.writer is None:
            from scripts.file_write_guard import safe_write_text
            writer = safe_write_text
        else:
            writer = self.writer
        path.parent.mkdir(parents=True, exist_ok=True)
        writer(path, content, "Growth", "growth-projection", self.runtime_path('backups'))

    def runtime_path(self, name):
        path = self.runtime / name
        if not path.resolve().is_relative_to(self.runtime):
            raise ValueError('growth runtime path escapes its dedicated directory')
        return path

    def _rows(self, name):
        path = self.path(name)
        if not path.exists():
            return []
        return self._parse_rows(path.read_bytes())

    def _parse_rows(self, content):
        rows = [json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("growth source must contain JSON objects")
        return rows

    @property
    def events_name(self):
        return "50-Agent-Workflows/90-Logs/growth-evaluation-events.jsonl"

    def receipts(self):
        formal = self._rows("50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl")
        for row in formal:
            if row.get("schema_version") == 3:
                require_valid_formal_receipt(row)
        identities = {r.get("receipt_id") for r in formal}
        standalone = [r for r in self._rows(".memory-hub/events/task-events.jsonl")
            if not r.get("project") and r.get("receipt_id") not in identities]
        unique, legacy = {}, []
        for row in formal + standalone:
            identity = row.get('receipt_id')
            if not identity:
                if (row.get('schema_version') or 0) >= 2:
                    raise ValueError('tracked receipt requires receipt_id')
                legacy.append(row); continue
            if identity in unique and _json(unique[identity]) != _json(row):
                raise ValueError('receipt identity conflict')
            unique[identity] = row
        return legacy + list(unique.values())

    @contextmanager
    def _lock(self):
        lock = self.runtime_path('growth.lock')
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        try:
            yield
        finally:
            lock.unlink()

    def assess(self, receipt, *, events=(), impact="unknown", impact_reason="", reviewer=None):
        if self.mode != "enabled":
            return {"mode": self.mode, "review_state": "disabled", "classification_state": "unassessed"}
        names = tuple(normalize_growth_event(event, config=DEFAULT_RULES) for event in events)
        requested = evaluate_trigger(GrowthInput(task=receipt['task'], summary='', events=names,
            impact=impact, impact_reason=impact_reason))  # Invalid input fails before any write.
        receipts = self.receipts()  # Invalid formal receipts are not a derived-only failure.
        try:
            self._checkpoint(receipts)
            source_events = tuple(self._rows(self.events_name))
            feedback_events = self._linked_feedback(receipts)
        except (ValueError, OSError, UnicodeError) as exc:
            if isinstance(exc, SourceContinuityError) and exc.source in {
                    '50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl', '.memory-hub/events/task-events.jsonl'}:
                raise
            return {**asdict(requested), 'mode': 'enabled', 'core_version': __version__, 'events': list(names),
                'review_state': 'pending_storage', 'increment_state': 'unknown', 'evidence_state': 'unknown',
                'outcome_state': 'unknown', 'pattern_key': '', 'methodology_candidate': '',
                'methodology_decision': '暂缓', 'methodology_reason': '成长历史暂不可校验；正式收工可保存，修复后重放。'}
        prior = tuple(r['event'] for r in source_events if r.get('task_id') == receipt['task_id'])
        if any(source['task_id'] == receipt['task_id'] and event['data'].get('growth_observation', {}).get('confirmed_omission')
                for source, event in feedback_events):
            prior += ('user_confirmed_omission',)
        history = tuple(dict(task_id=r['task_id'], task=r.get('task', ''), event='close',
            identity_state=r.get('identity_state', 'legacy_tracked'), payload=r.get('growth') or {})
            for r in receipts if r.get('task_id'))
        refs = receipt.get("evidence", ())
        if isinstance(refs, str):
            refs = tuple(s.strip() for s in re.split(r"[;；]", refs) if s.strip() and s.strip() != "无")
        value = GrowthInput(task=receipt["task"], summary=" | ".join(str(receipt.get(k, ""))
            for k in ("completed", "verification", "risks", "avoid_repeat")), events=prior + names,
            impact=impact, impact_reason=impact_reason, evidence_refs=tuple(refs))
        # An automatically generated identifier is not proof of an independent Episode.
        counted = history if receipt.get("identity_state") != "identity_unresolved" else ()
        result = dict(review_task(value, task_id=receipt["task_id"], history=counted, reviewer=reviewer).receipt_payload)
        if receipt.get("identity_state") == "identity_unresolved" and result["review_state"] == "completed":
            result.update(methodology_decision="暂缓", methodology_reason="任务身份未明确；不能计独立方法案例。")
        return {**result, "mode": "enabled", "core_version": __version__, "events": list(names)}

    def review_request(self, receipt_id):
        """Return an evidence-scoped prompt for an existing Agent; no model call."""
        if self.mode != "enabled":
            raise ValueError("enable growth recording explicitly before requesting a review")
        receipt = next((r for r in self.receipts() if r.get("receipt_id") == receipt_id), None)
        if not receipt:
            raise ValueError("original receipt not found")
        refs = receipt.get("evidence", ())
        if isinstance(refs, str):
            refs = tuple(s.strip() for s in re.split(r"[;；]", refs) if s.strip() and s.strip() != "无")
        value = GrowthInput(task=receipt["task"], summary=" | ".join(str(receipt.get(k, ""))
            for k in ("completed", "verification", "risks", "avoid_repeat")),
            events=("user_requested_retrospective",), evidence_refs=tuple(refs))
        return build_review_prompt(value, evaluate_trigger(value))

    def _pending(self):
        path = self.runtime_path('growth-pending.json')
        value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(value, dict):
            raise ValueError('invalid growth pending outbox')
        return value

    def _state(self):
        path = self.runtime_path('growth-state.json')
        if not path.exists():
            return {}
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('schema_version') != 1:
            raise ValueError('unsupported growth state; preserve the original snapshot')
        claimed = value.get('state_hash')
        if claimed != _sha(_json({k: v for k, v in value.items() if k != 'state_hash'})):
            raise ValueError('growth state hash validation failed')
        return value

    def _save_state(self, state):
        value = {k: v for k, v in state.items() if k != 'state_hash'}
        self._write(self.runtime_path('growth-state.json'), _json({**value, 'state_hash': _sha(_json(value))}) + '\n')

    def initialize(self):
        if self.mode != 'enabled':
            return dict(state='disabled', mode=self.mode)
        with self._lock():
            self._save_state(self._checkpoint(self.receipts()))
        return dict(state='initialized', runtime_root=str(self.runtime), core_version=__version__)

    def _checkpoint(self, receipts):
        prior = self._state()
        for name, checkpoint in prior.get("source_checkpoints", {}).items():
            source = self.path(name)
            content = source.read_bytes() if source.exists() else b""
            count = checkpoint["byte_count"]
            if type(count) is not int or count < 0 or count > len(content) or _sha(content[:count]) != checkpoint["sha256"]:
                raise SourceContinuityError(name)
        source = self.path(self.events_name)
        content = source.read_bytes() if source.exists() else b""
        task_ids = {r.get("task_id") for r in receipts if r.get("task_id")}
        events = tuple(r for r in self._parse_rows(content) if r.get("task_id") in task_ids)
        plan = project_admissions(events, prior_document=prior, source_id=str(source.resolve()), source_bytes=content)
        unique = {}
        for event in plan.events:
            identity = event.get("event_id")
            if not isinstance(identity, str) or not identity:
                raise ValueError("growth event requires event_id")
            if identity in unique and _json(unique[identity]) != _json(event):
                raise ValueError("growth event identity conflict")
            unique[identity] = event
        retained = list(unique.values())
        before = prior.get("growth_events", [])
        if retained[:len(before)] != before:
            raise ValueError("accepted growth prefix was changed")
        checkpoints = {}
        for name in ("50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl",
                ".memory-hub/events/task-events.jsonl", "50-Agent-Workflows/90-Logs/work-cycle.jsonl"):
            path = self.path(name)
            if path.exists():
                raw = path.read_bytes()
                checkpoints[name] = {"byte_count": len(raw), "sha256": _sha(raw)}
        return {"schema_version": 1, "core_version": __version__, "growth_events": retained,
            "growth_source_checkpoint": plan.source_checkpoint, "source_checkpoints": checkpoints,
            'processed_feedback_ids': list(prior.get('processed_feedback_ids', []))}

    def _append_event(self, *, receipt, event, identity, timestamp, payload):
        rows = self._rows(self.events_name)
        if any(r.get("event_id") == identity for r in rows):
            return
        row = dict(schema_version=1, event_id=identity, task_id=receipt["task_id"],
            timestamp=timestamp, task=receipt["task"], agent=receipt.get("agent", ""), event=event, payload=payload)
        target = self.path(self.events_name)
        old = target.read_bytes().decode("utf-8") if target.exists() else ""
        self._write(target, old + _json(row) + "\n")

    def _feedback(self):
        rows = self._rows("50-Agent-Workflows/90-Logs/work-cycle.jsonl")
        for row in rows:
            if row.get("record_hash") != _sha(_json({k: v for k, v in row.items() if k != "record_hash"})):
                raise ValueError("work-cycle feedback hash validation failed")
        return [r for r in rows if r.get("action") == "review"]

    def _linked_feedback(self, receipts):
        return linked_feedback_records(receipts, self._rows('50-Agent-Workflows/90-Logs/work-cycle.jsonl'))

    def _feedback_event(self, source, event):
        if event['data'].get('growth_observation', {}).get('confirmed_omission'):
            self._append_event(receipt=source, event='user_confirmed_omission', identity='GE-' + _sha(event['event_id'])[:24],
                timestamp=event['timestamp'], payload={'feedback_event_id': event['event_id'], 'receipt_id': source['receipt_id']})

    def task_rows(self):
        latest = {}
        receipts = self.receipts()
        by_receipt = {r.get("receipt_id"): r for r in receipts}
        for row in sorted(receipts, key=lambda r: _instant(r.get("timestamp")) or float("-inf")):
            if row.get("task_id") and (row.get("schema_version") or 0) >= 2:
                latest[row["task_id"]] = dict(row)
        feedback = {}
        linked = self._linked_feedback(receipts)
        unlinked = len(self._feedback()) - len(linked)
        for source, event in linked:
            feedback.setdefault(source['task_id'], []).append(event)
        result = []
        for identity, receipt in latest.items():
            growth = dict(receipt.get("growth") or {})
            if growth.get('review_state') == 'pending_storage':
                growth = self.assess(receipt, events=tuple(growth.get('events', ())),
                    impact=growth.get('impact', 'unknown'), impact_reason=growth.get('impact_reason', ''))
                growth['read_only_reclassification'] = True
            task_feedback = feedback.get(identity, [])
            event = task_feedback[-1] if task_feedback else None
            data = event["data"] if event else {}
            same_version = data.get("delivery", {}).get("episode_ref", {}).get("receipt_id") == receipt["receipt_id"]
            observation = data.get("growth_observation", {}) if same_version else {}
            closed_at = _instant(receipt.get("timestamp"))
            needs_review = False
            for observed in task_feedback:
                observed_ref = observed['data'].get('delivery', {}).get('episode_ref', {})
                observed_at = _instant(observed['timestamp'])
                if observed['data'].get('growth_observation', {}).get('confirmed_omission') and (
                        observed_ref.get('receipt_id') == receipt['receipt_id'] or observed_at is None or closed_at is None or observed_at > closed_at):
                    needs_review = True
            if needs_review:
                growth.update(review_required=True, review_state="pending_llm", methodology_decision="暂缓",
                    trigger_codes=list(dict.fromkeys(list(growth.get("trigger_codes", [])) + ["USER_CONFIRMED_OMISSION"])))
            result.append({**receipt, "growth": growth,
                "adoption_state": data.get("status", "unknown"), "outcome_state": observation.get("outcome_state", "unknown"),
                "protocol_verdict": observation.get("protocol_verdict", "unassessed"),
                "feedback_receipt_id": data.get("delivery", {}).get("episode_ref", {}).get("receipt_id", "")})
        return result, unlinked

    def report_rows(self):
        """Keep every receipt version; month projection performs its own dedupe."""
        latest, _ = self.task_rows()
        overlays = {row["receipt_id"]: row for row in latest}
        return [overlays.get(row.get("receipt_id"), row) for row in self.receipts()]

    def view(self):
        if self.mode != "enabled":
            return dict(mode=self.mode, status="disabled", core_version=__version__, tasks=[], methods=[],
                note="成长记录未启用；不会调用模型或修改全局规则。")
        receipts = self.receipts()
        self._checkpoint(receipts)  # Read-only validation; never silently heal a changed source.
        rows, unlinked = self.task_rows()
        methods = {}
        for row in rows:
            growth = row.get("growth") or {}
            if growth.get("pattern_key") and growth.get("review_state") == "completed":
                methods[growth["pattern_key"]] = dict(pattern_key=growth["pattern_key"],
                    title=growth.get("methodology_candidate", ""), state="pending_revalidation",
                    task_id=row["task_id"], evidence_refs=growth.get("evidence_refs", []),
                    card=growth.get("methodology_card", ""))
        verdicts = [r["protocol_verdict"] for r in rows if r["protocol_verdict"] in {"hit", "miss", "unnecessary"}]
        pending = self._pending()
        processed = set(self._state().get('processed_feedback_ids', []))
        for source, event in self._linked_feedback(receipts):
            if event['event_id'] not in processed:
                pending.setdefault('feedback:' + event['event_id'], dict(receipt_id=source['receipt_id'], kind='feedback'))
        initialized = self.runtime_path('growth-state.json').exists()
        return dict(mode="enabled", status="pending" if pending else ('ready' if initialized else 'uninitialized'), core_version=__version__,
            installed=True, enabled=True, state_initialized=initialized, runtime_root=str(self.runtime),
            reviewer='external_response_adapter', advanced_memory_runtime='not_public', effectiveness='not_established',
            tasks=rows, methods=list(methods.values()), pending=len(pending), pending_receipts=list(pending),
            unlinked_feedback=unlinked, metrics=dict(tasks=len(rows), assessed=len(verdicts),
                hit=verdicts.count("hit"), missed=verdicts.count("miss"), unnecessary=verdicts.count("unnecessary"),
                unknown_outcome=sum(r["outcome_state"] == "unknown" for r in rows),
                pending_reviews=sum(bool((r.get("growth") or {}).get("review_required"))
                    and (r.get("growth") or {}).get("review_state") != "completed" for r in rows)),
            reports=[dict(path=str(p), month=p.name[:7]) for p in sorted(self.path("90-Reviews").glob("*-AI协作质量月度评估.md"))],
            note="命中/漏判/无效打扰仅统计明确登记的评估，不是自动评分；采用不等于效果验证，本区方法候选均待独立复验。")

    def refresh_reports(self, months):
        rows = self.report_rows()
        events = self._rows(self.events_name)
        for month in sorted(set(months)):
            if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", month):
                raise ValueError("invalid report month")
            report = self.path(f"90-Reviews/{month}-AI协作质量月度评估.md")
            summary = summarize_month(rows, events, month=month)
            summary.update(receipts_source="formal receipts + standalone task events; read-only projection",
                events_source=str(self.path(self.events_name)))
            summary["source_hashes"] = {str(self.path(name)): _sha(self.path(name).read_bytes())
                for name in ("50-Agent-Workflows/90-Logs/memory-close-receipts.jsonl",
                    ".memory-hub/events/task-events.jsonl", self.events_name,
                    "50-Agent-Workflows/90-Logs/work-cycle.jsonl") if self.path(name).exists()}
            content = render_report(summary, generated_at=datetime.now().astimezone().isoformat(),
                schema_start=default_schema_start(month))
            if report.exists():
                preserve_evaluation_sections(report, report.read_text(encoding="utf-8"), "Growth", writer=self._write_eval)
            content = project_evaluation_events(content, read_evaluation_events(report))
            self._write(report, content)

    def _write_eval(self, path, content, *args):
        self._write(path, content)

    def after_receipt(self, receipt_id):
        if self.mode != "enabled":
            return dict(state="disabled", mode=self.mode)
        try:
            with self._lock():
                receipts = self.receipts()
                receipt = next((r for r in receipts if r.get("receipt_id") == receipt_id), None)
                if not receipt:
                    raise ValueError("original receipt not found")
                self._checkpoint(receipts)
                rows = self._rows(self.events_name)
                already_closed = any(r.get("event") == "close" and (r.get("payload") or {}).get("receipt_id") == receipt_id for r in rows)
                if not already_closed:
                    growth = receipt.get("growth") or {}
                    for sequence, name in enumerate(tuple(growth.get("events", ())) + ("close",)):
                        name = normalize_growth_event(name, config=DEFAULT_RULES)
                        payload = {'receipt_id': receipt_id}
                        if name == 'close':
                            payload.update({key: growth[key] for key in ('review_state', 'pattern_key', 'methodology_decision') if key in growth})
                        self._append_event(receipt=receipt, event=name,
                            identity="GE-" + _sha(f"{receipt_id}|{sequence}|{name}")[:24],
                            timestamp=receipt["timestamp"], payload=payload)
                state = self._checkpoint(receipts)
                processed = set(state.get('processed_feedback_ids', []))
                extra_months = set()
                for source, event in self._linked_feedback(receipts):
                    if source['task_id'] == receipt['task_id']:
                        self._feedback_event(source, event)
                        processed.add(event['event_id'])
                        extra_months.update((source['timestamp'][:7], event['timestamp'][:7]))
                state = self._checkpoint(receipts)
                state['processed_feedback_ids'] = sorted(processed)
                month = receipt["timestamp"][:7]
                report = self.path(f"90-Reviews/{month}-AI协作质量月度评估.md")
                record_event_file(report, event_date=receipt["timestamp"][:10], task=receipt["task"],
                    task_id=receipt["task_id"], agent=receipt.get("agent", ""), action="close",
                    evidence=str(receipt.get("evidence", "")), notes=receipt.get("completed", ""), writer=self._write_eval)
                self.refresh_reports(set(affected_report_months(receipts, receipt_id)) | extra_months)
                growth = receipt.get("growth") or {}
                if growth.get("methodology_decision") == "沉淀" and growth.get("pattern_key") and not growth.get("methodology_card"):
                    card = self.path("50-Agent-Workflows/10-SOP/Growth-" + _sha(growth["pattern_key"])[:16] + ".md")
                    if not card.exists():
                        self._write(card, f"# {growth.get('methodology_candidate', '候选方法')}\n\n状态：待复验，不是正式 Policy。\n\n"
                            + f"模式：{growth['pattern_key']}\n\n停止规则：{growth.get('new_stop_rule', '')}\n\n证据：{growth.get('evidence_refs', [])}\n")
                self._save_state(state)
                pending = self._pending()
                pending.pop(receipt_id, None)
                for identity in processed:
                    pending.pop('feedback:' + identity, None)
                self._write(self.runtime_path('growth-pending.json'), _json(pending) + "\n")
                return dict(state="synchronized", receipt_id=receipt_id, pending=len(pending))
        except Exception as exc:
            # A successful formal close is never rolled back by a derived failure.
            try:
                with self._lock():
                    pending = self._pending()
                    pending[receipt_id] = dict(receipt_id=receipt_id, error=str(exc),
                        recovery="修复来源/权限问题后按原 receipt_id 重放；不排序、不改写旧历史。")
                    self._write(self.runtime_path('growth-pending.json'), _json(pending) + "\n")
            except Exception:
                pass
            return dict(state="pending", receipt_id=receipt_id, error=str(exc),
                recovery="原收工已保存；保留源历史，修复后按原回执重放。")

    def after_feedback(self, event):
        if self.mode != "enabled":
            return dict(state="disabled", mode=self.mode)
        ref = event.get("data", {}).get("delivery", {}).get("episode_ref", {})
        receipt = next((r for r in self.receipts() if r.get("receipt_id") == ref.get("receipt_id")), None)
        if not receipt or receipt.get('schema_version') != 3 or not receipt.get('record_hash') or receipt.get("task_id") != ref.get("task_id") or receipt.get("record_hash") != ref.get("record_hash"):
            return dict(state="unlinked", reason="反馈已保存，但没有可靠 Episode 引用；不猜测任务身份。")
        try:
            with self._lock():
                self._checkpoint(self.receipts())
                # The primary decision ledger is the durable trigger/outbox.
                # Only a formal closure/replay flushes it to the growth log;
                # the UI must not race the private formal writer on that log.
                self.refresh_reports([receipt["timestamp"][:7], event["timestamp"][:7]])
                state = self._checkpoint(self.receipts())
                state['processed_feedback_ids'] = sorted(set(state.get('processed_feedback_ids', [])) | {event['event_id']})
                self._save_state(state)
                pending = self._pending()
                pending.pop('feedback:' + event['event_id'], None)
                self._write(self.runtime_path('growth-pending.json'), _json(pending) + '\n')
            return dict(state="recorded", task_id=receipt["task_id"], outcome_state=event['data'].get('growth_observation', {}).get('outcome_state', 'unknown'),
                outcome_evidence_state='reported_not_independently_verified',
                reason="反馈是证据；不自动验证结果或晋升方法。")
        except Exception as exc:
            try:
                with self._lock():
                    pending = self._pending()
                    pending['feedback:' + event['event_id']] = dict(receipt_id=receipt['receipt_id'],
                        feedback_event_id=event['event_id'], error=str(exc), recovery='按原回执重放，不重新发送用户决定。')
                    self._write(self.runtime_path('growth-pending.json'), _json(pending) + '\n')
            except Exception:
                pass  # The authoritative feedback row is also a durable outbox.
            return dict(state="pending", error=str(exc), receipt_id=receipt['receipt_id'], reason="用户决定已保存；成长投影待恢复。")


def enrich_growth(snapshot, config):
    """Add honest states; unavailable growth must not break the existing workbench."""
    try:
        snapshot["growth"] = GrowthWorkspace(config).view()
    except Exception as exc:
        snapshot["growth"] = dict(mode=config.get("growth_mode", "legacy_unconfigured"),
            status="integrity_error", error=str(exc), tasks=[], methods=[],
            note="未改写任何历史；保留原快照并修复来源后按原回执重放。")
    return snapshot

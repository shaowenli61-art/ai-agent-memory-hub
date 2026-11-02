"""Source byte continuity and stable admission projection; no writes."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from typing import Any


@dataclass(frozen=True)
class AdmissionPlan:
    events: tuple[dict[str, Any], ...]
    source_checkpoint: dict[str, Any]


def project_admissions(
    events: tuple[dict[str, Any], ...],
    *,
    prior_document: dict[str, Any],
    source_id: str,
    source_bytes: bytes,
) -> AdmissionPlan:
    """Keep admission order stable while separately validating physical history."""
    previous_checkpoint = prior_document.get('growth_source_checkpoint')
    if previous_checkpoint is not None:
        count = previous_checkpoint.get('byte_count')
        if (type(count) is not int or count < 0 or count > len(source_bytes)
                or previous_checkpoint.get('source') != source_id
                or hashlib.sha256(source_bytes[:count]).hexdigest() != previous_checkpoint.get('sha256')):
            raise ValueError('growth source log is not an append-only continuation')
    previous_events = prior_document.get('growth_events', ())
    previous_ids = [str(event['event_id']) for event in previous_events]
    previous_set = set(previous_ids)
    retained = tuple(event for event in events if str(event.get('event_id', '')) in previous_set)
    admitted = tuple(event for event in events if str(event.get('event_id', '')) not in previous_set)
    observed = list(dict.fromkeys(str(event['event_id']) for event in retained))
    if set(observed) != previous_set:
        raise ValueError('growth event stream is missing a prior accepted event')
    if previous_checkpoint is None:
        # Legacy snapshots used physical order. Verify it before recording the
        # first source-byte checkpoint; never silently migrate a changed prefix.
        if observed != previous_ids:
            raise ValueError('legacy growth event source order is not an append-only continuation')
        previous_tasks = {str(row.get('task_id', '')).strip() for row in prior_document.get('receipt_stream', ())}
        last_retained = max((i for i, event in enumerate(events) if str(event.get('event_id', '')) in previous_set), default=-1)
        if any(str(event.get('event_id', '')) not in previous_set and str(event.get('task_id', '')).strip() in previous_tasks for event in events[:last_retained]):
            raise ValueError('legacy growth source inserted an event for an already admitted task')
    # Use current source objects, NOT old snapshot copies. Core identity and
    # canonical prefix checks therefore still reject edits and conflicts.
    buckets = {identity: [] for identity in previous_ids}
    for event in retained:
        buckets[str(event['event_id'])].append(event)
    projected = tuple(event for identity in previous_ids for event in buckets[identity]) + admitted
    checkpoint = {'schema_version': 1, 'source': source_id,
                  'byte_count': len(source_bytes), 'sha256': hashlib.sha256(source_bytes).hexdigest()}
    return AdmissionPlan(projected, checkpoint)

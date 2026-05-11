"""Scripted-connectivity sync manager for PAC-AI offline simulation.

Given an OfflineQueue populated by a flow run, replay the scripted
connectivity timeline and drain the queue during online intervals. On each
drain:

* Verify that each envelope's ``predecessor_hash`` matches the previous
  envelope's ``content_hash`` in the same context → **chain_broken** if not.
* Re-compute the ``content_hash`` of the envelope JSON and compare to the
  stored hash → **tampered** if not.
* Flag envelopes whose ``queued_at`` is older than the connectivity window
  they drain in by more than ``late_after_seconds`` as **late**.
* POST successful drains to the upstream client (normally a MockUpstreamClient
  in simulation; can be the production JHContextClient if you want to
  drain against the real API).

The connectivity schedule is a list of (iso_timestamp, state) events with
state in ``{"online", "offline"}``. The manager is fully deterministic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .offline_queue import OfflineQueue, QueuedEnvelope


# ---------------------------------------------------------------------------
# Connectivity schedule
# ---------------------------------------------------------------------------
@dataclass
class ConnectivityEvent:
    at: datetime
    online: bool

    @classmethod
    def from_iso(cls, iso: str, state: str) -> ConnectivityEvent:
        return cls(at=_parse_iso(iso), online=state.lower() == "online")


class ConnectivityTimeline:
    """Ordered, gap-free connectivity events.

    An implicit ``offline`` state is assumed before the first event.
    Timeline entries are half-open: state at time ``t`` is the state of
    the most recent event with ``at <= t``.
    """

    def __init__(self, events: list[ConnectivityEvent]) -> None:
        self.events = sorted(events, key=lambda e: e.at)

    def is_online(self, at: datetime) -> bool:
        state = False
        for ev in self.events:
            if ev.at <= at:
                state = ev.online
            else:
                break
        return state

    def next_online_window(self, after: datetime) -> tuple[datetime, datetime] | None:
        """Return the next (start, end) online window covering or following *after*.

        If the timeline is already online at *after* (i.e., the most recent
        event with ``at <= after`` is ``online``), return ``(after, end)``
        where *end* is the next offline transition (or a far-future sentinel
        for an open-ended tail). Otherwise scan forward for the next online
        start. This matches the half-open semantics documented on
        ``ConnectivityTimeline`` — past events define current state.
        """
        if self.is_online(after):
            for ev in self.events:
                if ev.at <= after:
                    continue
                if not ev.online:
                    return (after, ev.at)
            return (after, datetime.max.replace(tzinfo=timezone.utc))

        start: datetime | None = None
        for ev in self.events:
            if ev.at < after:
                continue
            if ev.online and start is None:
                start = ev.at
            elif not ev.online and start is not None:
                return (start, ev.at)
        if start is not None:
            return (start, datetime.max.replace(tzinfo=timezone.utc))
        return None


# ---------------------------------------------------------------------------
# Upstream client protocol
# ---------------------------------------------------------------------------
class UpstreamClient(Protocol):
    def submit_envelope(self, envelope_json: str) -> None: ...
    def submit_prov(self, context_id: str, prov_ttl: str) -> None: ...


# ---------------------------------------------------------------------------
# Drain result
# ---------------------------------------------------------------------------
@dataclass
class DrainReport:
    drained: int = 0
    tampered: int = 0
    chain_broken: int = 0
    late: int = 0
    total_attempts: int = 0
    per_envelope: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "drained": self.drained,
            "tampered": self.tampered,
            "chain_broken": self.chain_broken,
            "late": self.late,
            "total_attempts": self.total_attempts,
            "per_envelope": self.per_envelope,
        }


# ---------------------------------------------------------------------------
# Sync manager
# ---------------------------------------------------------------------------
class SyncManager:
    """Drain an OfflineQueue using a deterministic connectivity timeline."""

    def __init__(
        self,
        queue: OfflineQueue,
        timeline: ConnectivityTimeline,
        upstream: UpstreamClient,
        *,
        late_after_seconds: float = 6 * 3600.0,
    ) -> None:
        self.queue = queue
        self.timeline = timeline
        self.upstream = upstream
        self.late_after_seconds = late_after_seconds

    def run(self) -> DrainReport:
        """Replay the timeline and drain the queue.

        Algorithm:
            1. For each pending envelope (ordered by queued_at):
               - determine the next online window at/after queued_at
               - if no window exists, leave pending (it's stuck offline)
               - otherwise drain it within that window:
                   * verify content_hash
                   * verify predecessor_hash against previous synced envelope
                     in the same context_id
                   * flag late if (drain_time - queued_at) > threshold
                   * mark_synced / mark_status accordingly
                   * POST to upstream on success
        """
        report = DrainReport()
        pending = self.queue.pending()

        # Track last-synced content hash per context for chain verification
        last_hash_per_context: dict[str, str] = {}

        for env in pending:
            report.total_attempts += 1
            queued_at = _parse_iso(env.queued_at)
            window = self.timeline.next_online_window(queued_at)
            if window is None:
                # Remains pending — no online window reached after queueing.
                self.queue.log_event(
                    "still_pending",
                    context_id=env.context_id,
                    envelope_id=env.envelope_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    details={"step": env.step_name, "reason": "no online window after queue time"},
                )
                continue

            drain_at = window[0]

            # Tamper check: re-hash the stored envelope_json and compare
            re_hash = _sha256(env.envelope_json)
            if re_hash != env.content_hash:
                self._record(
                    env, report, "tampered", drain_at,
                    {"expected": env.content_hash, "actual": re_hash},
                )
                self.queue.mark_status(env.envelope_id, "tampered")
                continue

            # Chain check: predecessor_hash must match last synced in this context
            prev = last_hash_per_context.get(env.context_id)
            if env.predecessor_hash is None:
                # First envelope in the context — accept; seed chain.
                pass
            elif prev is None:
                self._record(
                    env, report, "chain_broken", drain_at,
                    {"expected_predecessor": env.predecessor_hash,
                     "actual_predecessor": None,
                     "reason": "no prior synced envelope in context"},
                )
                self.queue.mark_status(env.envelope_id, "chain_broken")
                continue
            elif prev != env.predecessor_hash:
                self._record(
                    env, report, "chain_broken", drain_at,
                    {"expected_predecessor": env.predecessor_hash,
                     "actual_predecessor": prev},
                )
                self.queue.mark_status(env.envelope_id, "chain_broken")
                continue

            # Late-arrival check
            is_late = (drain_at - queued_at).total_seconds() > self.late_after_seconds

            # Submit upstream (never blocks the local audit path)
            try:
                self.upstream.submit_envelope(env.envelope_json)
                self.upstream.submit_prov(env.context_id, env.prov_ttl)
            except Exception as exc:  # pragma: no cover — mock client doesn't raise
                self._record(
                    env, report, "upstream_error", drain_at,
                    {"error": str(exc)},
                )
                continue

            # Successful drain
            if is_late:
                report.late += 1
                status = "late"
            else:
                status = "synced"
            report.drained += 1
            self.queue.mark_synced(env.envelope_id, synced_at=drain_at.isoformat())
            if status == "late":
                # Override drain_status to 'late' but keep synced_at set
                self.queue.mark_status(env.envelope_id, "late")

            self._record(env, report, status, drain_at, None)
            last_hash_per_context[env.context_id] = env.content_hash

        return report

    def _record(
        self,
        env: QueuedEnvelope,
        report: DrainReport,
        event: str,
        drain_at: datetime,
        details: dict[str, Any] | None,
    ) -> None:
        if event == "tampered":
            report.tampered += 1
        elif event == "chain_broken":
            report.chain_broken += 1
        entry = {
            "envelope_id": env.envelope_id,
            "context_id": env.context_id,
            "step": env.step_name,
            "queued_at": env.queued_at,
            "drain_at": drain_at.isoformat(),
            "event": event,
            "details": details,
        }
        report.per_envelope.append(entry)
        self.queue.log_event(
            event_type=event,
            context_id=env.context_id,
            envelope_id=env.envelope_id,
            timestamp=drain_at.isoformat(),
            details=details or {"step": env.step_name},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_iso(s: str) -> datetime:
    # Accepts both "...Z" and "+00:00" forms.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _sha256(data: str | bytes) -> str:
    """SHA-256 hex digest, no prefix (matches jhcontext.crypto.compute_sha256)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def build_timeline(schedule: list[tuple[str, str]]) -> ConnectivityTimeline:
    """Convenience: build a timeline from [(iso, 'online'|'offline'), ...]."""
    return ConnectivityTimeline(
        [ConnectivityEvent.from_iso(iso, state) for iso, state in schedule]
    )

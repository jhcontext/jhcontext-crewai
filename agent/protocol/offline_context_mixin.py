"""Offline-aware CrewAI ↔ PAC-AI bridge.

Drop-in ContextMixin replacement used by the offline healthcare scenarios.
Instead of POSTing each envelope to the Chalice API in a background thread,
the mixin enqueues envelopes into a local ``OfflineQueue`` (SQLite file).
The ``SyncManager`` drains the queue later against a scripted
connectivity timeline.

Differences vs. ``ContextMixin``:

* ``_persist_task_callback`` writes to the local queue, never to the network.
* ``_persist_step`` / ``_persist_oversight_events`` do the same.
* Each enqueue computes ``content_hash`` (SHA-256 of the signed envelope JSON)
  and ``predecessor_hash`` (content_hash of the previously enqueued envelope
  in the same context), yielding the paper's predecessor-hash chain.
* No ``JHContextClient`` is instantiated — the upstream client is only used
  at drain time by the SyncManager.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jhcontext import (
    ArtifactType,
    EnvelopeBuilder,
    ForwardingEnforcer,
    ForwardingPolicy,
    PROVGraph,
    RiskLevel,
    StepPersister,
    compute_sha256,
)
from jhcontext.pii import InMemoryPIIVault

from .offline_queue import OfflineQueue


class OfflineContextMixin:
    """Mixin for CrewAI Flows with offline-first persistence.

    Usage::

        class TriageFlow(Flow, OfflineContextMixin):
            @start()
            def init(self):
                self._init_context(
                    scope="rural_cardiac_triage",
                    producer="did:hospital:physio-signal-agent",
                    risk_level=RiskLevel.HIGH,
                    queue_path="output/triage_rural_queue.sqlite",
                )
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _init_context(
        self,
        scope: str,
        producer: str,
        queue_path: Path | str,
        *,
        risk_level: RiskLevel = RiskLevel.HIGH,
        human_oversight: bool = True,
        feature_suppression: list[str] | None = None,
        reset_queue: bool = True,
    ) -> str:
        builder = EnvelopeBuilder()
        builder.set_producer(producer)
        builder.set_scope(scope)
        builder.set_risk_level(risk_level)
        builder.set_human_oversight(human_oversight)

        pii_vault = InMemoryPIIVault()
        if feature_suppression:
            builder.set_privacy(feature_suppression=feature_suppression)
            builder.enable_pii_detachment(vault=pii_vault)

        env = builder.build()
        context_id = env.context_id
        prov = PROVGraph(context_id=context_id)

        queue = OfflineQueue(queue_path, reset=reset_queue)

        self.state["_builder"] = builder
        self.state["_prov"] = prov
        self.state["_context_id"] = context_id
        self.state["_pii_vault"] = pii_vault
        self.state["_enforcer"] = ForwardingEnforcer(
            policy=env.compliance.forwarding_policy
        )
        self.state["_queue"] = queue
        # StepPersister is reused for metric bookkeeping; we pass None client.
        self.state["_persister"] = StepPersister(
            client=None, builder=builder, prov=prov, context_id=context_id,
        )
        self.state["_last_content_hash"] = None  # predecessor chain seed
        self.state["_total_start"] = time.time()
        self.state["_task_envelopes"] = []
        self.state["_scope"] = scope

        policy = env.compliance.forwarding_policy
        risk = env.compliance.risk_level.value
        self.state["_forwarding_preamble"] = policy.format_preamble(risk)

        return context_id

    def _register_crew(
        self,
        crew_id: str,
        label: str,
        agent_ids: list[str],
    ) -> None:
        prov: PROVGraph = self.state["_prov"]
        prov.add_crew(crew_id, label)
        for agent_id in agent_ids:
            prov.add_agent(agent_id, agent_id)
            prov.acted_on_behalf_of(agent_id, crew_id)

    # ------------------------------------------------------------------
    # Enqueue path (replaces ContextMixin's async thread POST)
    # ------------------------------------------------------------------
    def _enqueue_snapshot(
        self,
        agent_id: str,
        step_name: str,
    ) -> str:
        """Sign the current flow envelope + PROV, enqueue offline, return hash."""
        builder: EnvelopeBuilder = self.state["_builder"]
        prov: PROVGraph = self.state["_prov"]
        queue: OfflineQueue = self.state["_queue"]
        context_id: str = self.state["_context_id"]

        signed_env = builder.sign(agent_id).build()
        envelope_json = json.dumps(signed_env.to_jsonld(), ensure_ascii=False)
        content_hash = compute_sha256(envelope_json.encode("utf-8"))
        predecessor_hash = self.state.get("_last_content_hash")

        queue.enqueue(
            context_id=context_id,
            step_name=step_name,
            envelope_json=envelope_json,
            prov_ttl=prov.serialize("turtle"),
            content_hash=content_hash,
            predecessor_hash=predecessor_hash,
        )
        self.state["_last_content_hash"] = content_hash
        self.state["_task_envelopes"].append(signed_env.to_jsonld())
        return content_hash

    # ------------------------------------------------------------------
    # CrewAI task_callback — local-first persistence
    # ------------------------------------------------------------------
    def _persist_task_callback(self, output) -> None:
        """Equivalent to ContextMixin._persist_task_callback but enqueues
        to the OfflineQueue instead of POSTing to the API."""
        from jhcontext.models import Envelope as EnvelopeModel
        from jhcontext.flat_envelope import FlatEnvelope

        pydantic_out = getattr(output, "pydantic", None)
        raw = getattr(output, "raw", str(output))
        agent_name = getattr(output, "agent", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        builder: EnvelopeBuilder = self.state["_builder"]
        prov: PROVGraph = self.state["_prov"]
        enforcer: ForwardingEnforcer = self.state["_enforcer"]
        persister: StepPersister = self.state["_persister"]
        prev_artifacts = list(persister.step_artifacts)

        env: EnvelopeModel | None = None
        if isinstance(pydantic_out, EnvelopeModel):
            env = pydantic_out
        elif isinstance(pydantic_out, FlatEnvelope):
            env = pydantic_out.to_envelope()
        elif raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and (
                    "context_id" in data or "semantic_payload" in data
                ):
                    env = EnvelopeModel.model_validate(data)
            except (json.JSONDecodeError, Exception):
                pass

        if env is None:
            # Fallback: treat raw text as an opaque token sequence.
            desc = getattr(output, "description", "task")[:30].replace(" ", "_")
            artifact_id = f"art-task-{desc}"
            content_hash = compute_sha256(raw.encode("utf-8"))
            builder.add_artifact(
                artifact_id=artifact_id,
                artifact_type=ArtifactType.TOKEN_SEQUENCE,
                content_hash=content_hash,
            )
            prov.add_entity(
                artifact_id, f"Task output: {desc}",
                artifact_type="token_sequence", content_hash=content_hash,
            )
            persister.step_artifacts.append(artifact_id)
            self._enqueue_snapshot(agent_id=f"did:agent:{agent_name}",
                                   step_name=desc)
            return

        # ── Policy resolution + output filtering (SDK) ──
        policy = enforcer.resolve(env)

        step_name = "task"
        if env.artifacts_registry:
            step_name = env.artifacts_registry[-1].artifact_id.removeprefix("art-")
        elif env.scope:
            step_name = env.scope.split("_")[-1]

        payload_bytes = str(env.semantic_payload).encode("utf-8")
        content_hash = compute_sha256(payload_bytes)

        artifact_id = f"art-{step_name}"
        artifact_type = ArtifactType.SEMANTIC_EXTRACTION
        if env.artifacts_registry:
            last_art = env.artifacts_registry[-1]
            artifact_id = last_art.artifact_id
            artifact_type = last_art.type
            last_art.content_hash = content_hash

        agent_id = env.producer or f"did:agent:{agent_name}"

        output.raw = enforcer.filter_output(env, policy)

        builder.add_artifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content_hash=content_hash,
        )
        builder.set_passed_artifact(artifact_id)

        prov.add_agent(agent_id, agent_id, role=step_name)
        prov.add_entity(
            artifact_id,
            f"Task output: {step_name}",
            artifact_type=artifact_type.value,
            content_hash=content_hash,
        )
        activity_id = f"act-{step_name}"
        prov.add_activity(activity_id, step_name, started_at=now, ended_at=now)
        prov.was_generated_by(artifact_id, activity_id)
        prov.was_associated_with(activity_id, agent_id)
        if prev_artifacts:
            prev = prev_artifacts[-1]
            prov.used(activity_id, prev)
            prov.was_derived_from(artifact_id, prev)

        for di in env.decision_influence:
            builder.add_decision_influence(
                agent=di.agent,
                categories=di.categories,
                influence_weights=di.influence_weights,
            )

        persister.step_artifacts.append(artifact_id)
        persister.metrics.append(
            {
                "step": step_name,
                "agent": agent_id,
                "artifact_id": artifact_id,
                "content_size_bytes": len(payload_bytes),
                "persist_ms": 0,
                "started_at": now,
                "ended_at": now,
            }
        )

        # Enqueue the flow-level envelope (local-first, no network)
        self._enqueue_snapshot(agent_id=agent_id, step_name=step_name)

    # ------------------------------------------------------------------
    # Direct-call persist for non-CrewAI steps (oversight / audit)
    # ------------------------------------------------------------------
    def _persist_step(
        self,
        step_name: str,
        agent_id: str,
        output: str,
        artifact_type: ArtifactType,
        started_at: str,
        ended_at: str,
        used_artifacts: list[str] | None = None,
    ) -> str:
        builder: EnvelopeBuilder = self.state["_builder"]
        prov: PROVGraph = self.state["_prov"]
        persister: StepPersister = self.state["_persister"]

        content_hash = compute_sha256(output.encode("utf-8"))
        artifact_id = f"art-{step_name}"
        activity_id = f"act-{step_name}"

        builder.add_artifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            content_hash=content_hash,
        )
        builder.set_passed_artifact(artifact_id)

        prov.add_agent(agent_id, agent_id, role=step_name)
        prov.add_entity(
            artifact_id, f"Step: {step_name}",
            artifact_type=artifact_type.value, content_hash=content_hash,
        )
        prov.add_activity(
            activity_id, step_name,
            started_at=started_at, ended_at=ended_at,
        )
        prov.was_generated_by(artifact_id, activity_id)
        prov.was_associated_with(activity_id, agent_id)

        for used in used_artifacts or []:
            prov.used(activity_id, used)

        if persister.step_artifacts:
            prov.was_derived_from(artifact_id, persister.step_artifacts[-1])

        persister.step_artifacts.append(artifact_id)
        persister.metrics.append({
            "step": step_name,
            "agent": agent_id,
            "artifact_id": artifact_id,
            "content_size_bytes": len(output.encode("utf-8")),
            "persist_ms": 0,
            "started_at": started_at,
            "ended_at": ended_at,
        })

        self._enqueue_snapshot(agent_id=agent_id, step_name=step_name)
        return artifact_id

    def _persist_oversight_events(
        self,
        events: list[dict[str, Any]],
        oversight_agent_id: str,
        summary_output: str,
        overall_started_at: str,
        overall_ended_at: str,
    ) -> str:
        """Record fine-grained document-access events + summary artifact.

        Mirrors ContextMixin._persist_oversight_events but enqueues offline
        instead of calling the API.
        """
        builder: EnvelopeBuilder = self.state["_builder"]
        prov: PROVGraph = self.state["_prov"]
        persister: StepPersister = self.state["_persister"]

        prov.add_agent(oversight_agent_id, oversight_agent_id,
                       role="physician_oversight")

        accessed_entities = []
        for event in events:
            entity_id = event["accessed_entity"]
            entity_label = event.get("entity_label", entity_id)
            prov.add_entity(entity_id, entity_label, artifact_type="source_document")
            accessed_entities.append(entity_id)

            prov.add_activity(
                event["event_id"], event["label"],
                started_at=event["started_at"],
                ended_at=event["ended_at"],
            )
            prov.was_associated_with(event["event_id"], oversight_agent_id)
            prov.used(event["event_id"], entity_id)

        content_hash = compute_sha256(summary_output.encode("utf-8"))
        artifact_id = "art-oversight"
        builder.add_artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            content_hash=content_hash,
        )
        builder.set_passed_artifact(artifact_id)

        prov.add_entity(
            artifact_id, "Oversight summary",
            artifact_type="semantic_extraction", content_hash=content_hash,
        )
        oversight_activity_id = "act-oversight"
        prov.add_activity(
            oversight_activity_id, "physician_oversight",
            started_at=overall_started_at,
            ended_at=overall_ended_at,
        )
        prov.was_generated_by(artifact_id, oversight_activity_id)
        prov.was_associated_with(oversight_activity_id, oversight_agent_id)
        for entity_id in accessed_entities:
            prov.used(oversight_activity_id, entity_id)

        prev_artifacts = list(persister.step_artifacts)
        if prev_artifacts:
            prov.used(oversight_activity_id, prev_artifacts[-1])
            prov.was_derived_from(artifact_id, prev_artifacts[-1])

        persister.step_artifacts.append(artifact_id)
        persister.metrics.append({
            "step": "oversight",
            "agent": oversight_agent_id,
            "artifact_id": artifact_id,
            "content_size_bytes": len(summary_output.encode("utf-8")),
            "persist_ms": 0,
            "started_at": overall_started_at,
            "ended_at": overall_ended_at,
        })

        # Enqueue the oversight envelope (often queues during online tail)
        self._enqueue_snapshot(
            agent_id=oversight_agent_id, step_name="oversight",
        )
        return artifact_id

    def _log_decision(
        self,
        outcome: dict[str, Any],
        agent_id: str,
        alternatives: list[dict[str, Any]] | None = None,
    ) -> None:
        """Local PROV record of the decision (no upstream API call)."""
        prov: PROVGraph = self.state["_prov"]
        if alternatives:
            decision_activity = "act-decision-eval"
            prov.add_activity(
                decision_activity, "decision_evaluation",
                started_at=datetime.now(timezone.utc).isoformat(),
                ended_at=datetime.now(timezone.utc).isoformat(),
            )
            prov.was_associated_with(decision_activity, agent_id)
            for i, alt in enumerate(alternatives):
                alt_id = f"ent-alt-{i}"
                alt_label = alt.get("treatment", alt.get("label", f"alternative-{i}"))
                prov.add_entity(alt_id, alt_label,
                                artifact_type="decision_alternative")
                prov.used(decision_activity, alt_id)

    def _finalize_metrics(self) -> dict[str, Any]:
        persister: StepPersister = self.state["_persister"]
        return persister.finalize_metrics(self.state["_total_start"])

    def _cleanup(self) -> None:
        q = self.state.get("_queue")
        if q is not None:
            q.close()

"""CrewAI ↔ PAC-AI protocol bridge mixin.

Thin CrewAI-specific layer that delegates protocol logic to the jhcontext SDK:
- ``ForwardingEnforcer`` — monotonic policy resolution + output filtering
- ``StepPersister`` — artifact + envelope + PROV persistence orchestration
- ``ForwardingPolicy.format_preamble()`` — task instruction generation

The only CrewAI-specific code is ``_persist_task_callback``, which reads/writes
CrewAI's ``TaskOutput`` object (``output.pydantic``, ``output.raw``).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
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
from jhcontext.client.api_client import JHContextClient
from jhcontext.pii import InMemoryPIIVault

API_URL = os.environ.get("JHCONTEXT_API_URL", "http://localhost:8400")


class ContextMixin:
    """Mixin for CrewAI Flows that automatically persists PAC-AI envelopes.

    Usage::

        class MyFlow(Flow, ContextMixin):
            @start()
            def init(self):
                self._init_context(scope="healthcare", producer="did:hospital:system",
                                   risk_level=RiskLevel.HIGH)
    """

    def _init_context(
        self,
        scope: str,
        producer: str,
        risk_level: RiskLevel = RiskLevel.HIGH,
        human_oversight: bool = True,
        feature_suppression: list[str] | None = None,
    ) -> str:
        """Call in @start() — creates initial envelope + PROV.

        If *feature_suppression* is provided, PII detachment is automatically
        enabled — specified fields in the semantic payload will be tokenized
        before signing and persistence.
        """
        builder = EnvelopeBuilder()
        builder.set_producer(producer)
        builder.set_scope(scope)
        builder.set_risk_level(risk_level)
        builder.set_human_oversight(human_oversight)

        # PII detachment setup
        pii_vault = InMemoryPIIVault()
        if feature_suppression:
            builder.set_privacy(feature_suppression=feature_suppression)
            builder.enable_pii_detachment(vault=pii_vault)

        # Build to get context_id
        env = builder.build()
        context_id = env.context_id

        client = JHContextClient(base_url=API_URL)
        prov = PROVGraph(context_id=context_id)

        # SDK classes for protocol logic
        enforcer = ForwardingEnforcer()
        persister = StepPersister(
            client=client,
            builder=builder,
            prov=prov,
            context_id=context_id,
        )

        self.state["_builder"] = builder
        self.state["_prov"] = prov
        self.state["_context_id"] = context_id
        self.state["_api_client"] = client
        self.state["_pii_vault"] = pii_vault
        self.state["_enforcer"] = enforcer
        self.state["_persister"] = persister
        self.state["_total_start"] = time.time()

        # Generate preamble from the envelope's forwarding policy
        policy = env.compliance.forwarding_policy
        risk = env.compliance.risk_level.value
        self.state["_forwarding_preamble"] = policy.format_preamble(risk)

        return context_id

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
        """Call after each crew.kickoff() — delegates to SDK StepPersister."""
        persister: StepPersister = self.state["_persister"]
        return persister.persist(
            step_name=step_name,
            agent_id=agent_id,
            output=output,
            artifact_type=artifact_type,
            started_at=started_at,
            ended_at=ended_at,
            used_artifacts=used_artifacts,
        )

    def _persist_task_callback(self, output) -> None:
        """Task-level persistence via CrewAI task_callback.

        This is the only CrewAI-specific method — it reads ``output.pydantic``
        and ``output.raw`` from CrewAI's TaskOutput object.

        Two phases:
        1. **Synchronous** — resolve the effective forwarding policy via
           ``ForwardingEnforcer.resolve()``, rewrite ``output.raw`` via
           ``ForwardingEnforcer.filter_output()`` for Semantic-Forward.
           Also extends the flow-level builder and PROV graph.
        2. **Async** — persist the full envelope + PROV to the backend
           API in a background thread.

        For Raw-Forward, ``output.raw`` is left untouched.
        """
        from jhcontext.models import Envelope as EnvelopeModel
        from jhcontext.flat_envelope import FlatEnvelope

        pydantic_out = getattr(output, "pydantic", None)
        raw = getattr(output, "raw", str(output))
        agent_name = getattr(output, "agent", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        builder: EnvelopeBuilder = self.state["_builder"]
        prov: PROVGraph = self.state["_prov"]
        client: JHContextClient = self.state["_api_client"]
        context_id: str = self.state["_context_id"]
        enforcer: ForwardingEnforcer = self.state["_enforcer"]
        persister: StepPersister = self.state["_persister"]
        prev_artifacts = list(persister.step_artifacts)

        # --- Full Envelope path ---
        # Resolution order:
        # 1. output_pydantic=Envelope (full nested model)
        # 2. output_pydantic=FlatEnvelope (flat model → .to_envelope())
        # 3. Raw JSON parsed as Envelope (free-form LLM output fallback)
        env: EnvelopeModel | None = None
        if isinstance(pydantic_out, EnvelopeModel):
            env = pydantic_out
        elif isinstance(pydantic_out, FlatEnvelope):
            env = pydantic_out.to_envelope()
        elif raw:
            import json as _json
            try:
                data = _json.loads(raw)
                if isinstance(data, dict) and ("context_id" in data or "semantic_payload" in data):
                    env = EnvelopeModel.model_validate(data)
            except (_json.JSONDecodeError, Exception):
                pass

        if env is not None:

            # Per-task policy with monotonic enforcement (SDK)
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

            # ── Phase 1 (sync): rewrite output.raw + extend state ──

            # Structural enforcement: filter output based on resolved policy (SDK)
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

            # ── Phase 2 (async): persist full envelope to backend ──
            def _do_persist_envelope():
                signed_env = builder.sign(agent_id).build()
                client.submit_envelope(signed_env)
                client.submit_prov_graph(context_id, prov.serialize("turtle"))

            threading.Thread(target=_do_persist_envelope, daemon=True).start()
            return

        # --- Fallback: lightweight artifact-only persistence ---
        desc = getattr(output, "description", "task")[:30].replace(" ", "_")
        artifact_id = f"art-task-{desc}"
        content = raw.encode("utf-8")
        content_hash = compute_sha256(content)

        builder.add_artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.TOKEN_SEQUENCE,
            content_hash=content_hash,
        )

        prov.add_entity(
            artifact_id,
            f"Task output: {desc}",
            artifact_type="token_sequence",
            content_hash=content_hash,
        )

        persister.step_artifacts.append(artifact_id)

    def _get_latest_context(self) -> dict[str, Any]:
        """Retrieve latest envelope from API."""
        client: JHContextClient = self.state["_api_client"]
        return client.get_envelope(self.state["_context_id"])

    def _persist_oversight_events(
        self,
        events: list[dict[str, Any]],
        oversight_agent_id: str,
        summary_output: str,
        overall_started_at: str,
        overall_ended_at: str,
    ) -> str:
        """Persist fine-grained physician oversight events to the PROV graph.

        Each event represents a distinct document-access activity with its
        own timestamp, enabling ``verify_temporal_oversight()`` to validate
        meaningful human review per EU AI Act Article 14.

        Parameters
        ----------
        events:
            List of dicts, each with keys: ``event_id``, ``label``,
            ``started_at``, ``ended_at``, ``accessed_entity``,
            ``entity_label``.
        oversight_agent_id:
            DID of the physician performing the review.
        summary_output:
            The narrative oversight report (persisted as art-oversight).
        overall_started_at, overall_ended_at:
            Timestamps bounding the full oversight phase.
        """
        builder: EnvelopeBuilder = self.state["_builder"]
        prov: PROVGraph = self.state["_prov"]
        client: JHContextClient = self.state["_api_client"]
        context_id: str = self.state["_context_id"]
        persister: StepPersister = self.state["_persister"]

        # Add the oversight physician as a PROV agent
        prov.add_agent(oversight_agent_id, oversight_agent_id, role="physician_oversight")

        # Add source-document entities and access activities
        accessed_entities = []
        for event in events:
            entity_id = event["accessed_entity"]
            entity_label = event.get("entity_label", entity_id)
            prov.add_entity(entity_id, entity_label, artifact_type="source_document")
            accessed_entities.append(entity_id)

            activity_id = event["event_id"]
            prov.add_activity(
                activity_id, event["label"],
                started_at=event["started_at"],
                ended_at=event["ended_at"],
            )
            prov.was_associated_with(activity_id, oversight_agent_id)
            prov.used(activity_id, entity_id)

        # Create the summary oversight artifact
        content_hash = compute_sha256(summary_output.encode("utf-8"))
        artifact_id = "art-oversight"
        builder.add_artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            content_hash=content_hash,
        )
        builder.set_passed_artifact(artifact_id)

        prov.add_entity(
            artifact_id, "Physician oversight summary",
            artifact_type="semantic_extraction",
            content_hash=content_hash,
        )
        oversight_activity_id = "act-oversight"
        prov.add_activity(
            oversight_activity_id, "physician_oversight",
            started_at=overall_started_at,
            ended_at=overall_ended_at,
        )
        prov.was_generated_by(artifact_id, oversight_activity_id)
        prov.was_associated_with(oversight_activity_id, oversight_agent_id)

        # Link oversight summary to all accessed source documents
        for entity_id in accessed_entities:
            prov.used(oversight_activity_id, entity_id)

        # Link oversight to the clinical decision artifact
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

        # Persist in background
        def _do_persist():
            signed_env = builder.sign(oversight_agent_id).build()
            client.submit_envelope(signed_env)
            client.submit_prov_graph(context_id, prov.serialize("turtle"))

        threading.Thread(target=_do_persist, daemon=True).start()
        return artifact_id

    def _log_decision(
        self,
        outcome: dict[str, Any],
        agent_id: str,
        alternatives: list[dict[str, Any]] | None = None,
    ) -> str:
        """Log a decision via the API.

        If *alternatives* is provided, each alternative is added to the
        PROV graph as an entity linked to the decision activity, recording
        the decision-making context (options considered, not just outcome).
        """
        client: JHContextClient = self.state["_api_client"]
        persister: StepPersister = self.state["_persister"]
        prov: PROVGraph = self.state["_prov"]
        passed = persister.step_artifacts[-1] if persister.step_artifacts else None

        # Record alternatives in PROV graph
        if alternatives:
            decision_activity = f"act-decision-eval"
            prov.add_activity(
                decision_activity, "decision_evaluation",
                started_at=datetime.now(timezone.utc).isoformat(),
                ended_at=datetime.now(timezone.utc).isoformat(),
            )
            prov.was_associated_with(decision_activity, agent_id)
            for i, alt in enumerate(alternatives):
                alt_id = f"ent-alt-{i}"
                alt_label = alt.get("treatment", alt.get("label", f"alternative-{i}"))
                prov.add_entity(alt_id, alt_label, artifact_type="decision_alternative")
                prov.used(decision_activity, alt_id)

        return client.log_decision(
            context_id=self.state["_context_id"],
            passed_artifact_id=passed,
            outcome=outcome,
            agent_id=agent_id,
        )

    def _finalize_metrics(self) -> dict[str, Any]:
        """Collect timing metrics — delegates to SDK StepPersister."""
        persister: StepPersister = self.state["_persister"]
        return persister.finalize_metrics(self.state["_total_start"])

    def _cleanup(self) -> None:
        """Close API client."""
        client = self.state.get("_api_client")
        if client:
            client.close()

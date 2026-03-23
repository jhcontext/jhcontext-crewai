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
        if isinstance(pydantic_out, EnvelopeModel):
            env: EnvelopeModel = pydantic_out

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

    def _log_decision(
        self,
        outcome: dict[str, Any],
        agent_id: str,
    ) -> str:
        """Log a decision via the API."""
        client: JHContextClient = self.state["_api_client"]
        persister: StepPersister = self.state["_persister"]
        passed = persister.step_artifacts[-1] if persister.step_artifacts else None
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

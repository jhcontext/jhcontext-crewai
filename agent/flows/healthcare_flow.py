"""Healthcare Human Oversight Flow — Article 14 EU AI Act.

The clinical workflow is two *composed* pipelines (PAC-AI mixed-mode):

  raw_pipeline (raw_forward)        : sensor → ontology_classification
  semantic_pipeline (semantic_fwd)  : triage → allocation
  → physician_oversight → compliance_audit

The raw pipeline reads the raw signal and classifies it against a clinical
ontology; the full envelope crosses its internal handoff. Its terminal
artifact (the ontology-classified ``semantic_payload``) is fed as the input
to the semantic pipeline, whose handoffs are filtered to the
``semantic_payload`` only. Each pipeline runs under its own
``ForwardingEnforcer`` (swapped on ``self.state["_enforcer"]`` per stage),
so a raw-stage envelope declaring ``raw_forward`` no longer collides with a
semantic-stage enforcer — this is the documented way to compose modes.

Task-level persistence happens in parallel via ``_persist_task_callback`` —
each task's Envelope is signed and POSTed to the backend while the next task
runs. Physician oversight records 4 document-access activities in the PROV
graph with real timestamps, enabling ``verify_temporal_oversight()``.
"""

from __future__ import annotations

import json
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.healthcare.crew import (
    HealthcareAuditCrew,
    HealthcareOversightCrew,
    HealthcareRawCrew,
    HealthcareSemanticCrew,
)
from agent.protocol.context_mixin import ContextMixin

from jhcontext import ArtifactType, ForwardingEnforcer, ForwardingPolicy, RiskLevel
from jhcontext.audit import (
    generate_audit_report,
    verify_integrity,
    verify_temporal_oversight,
)

import agent.output_dir as _out

# Simulated document-access durations (seconds).
# Production would use real physician interaction times.
SOURCE_DOCUMENTS = [
    ("act-access-ct-scan", "Access CT scan", "ent-ct-scan", "CT scan metadata", 4),
    ("act-access-history", "Access treatment history", "ent-treatment-history", "Treatment history", 3),
    ("act-access-pathology", "Access pathology report", "ent-pathology", "Pathology report", 2),
    ("act-review-ai", "Review AI recommendation", "ent-ai-recommendation", "AI recommendation", 1),
]


class HealthcareFlow(Flow, ContextMixin):
    """Healthcare human oversight compliance flow.

    Demonstrates Article 14 compliance by recording the complete
    decision chain from sensor observations through physician review,
    with temporal evidence of meaningful human oversight.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="healthcare_treatment_recommendation",
            producer="did:hospital:system",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
        )

        # Register the two composed clinical pipelines in the PROV graph.
        # The physician (dr-chen) is intentionally outside both crews —
        # oversight must be external to the decision-making pipelines.
        self._register_crew(
            crew_id="crew:raw-pipeline",
            label="Raw-Forward Pipeline Crew",
            agent_ids=[
                "did:hospital:sensor-agent",
                "did:hospital:ontology-agent",
            ],
        )
        self._register_crew(
            crew_id="crew:semantic-pipeline",
            label="Semantic-Forward Pipeline Crew",
            agent_ids=[
                "did:hospital:triage-agent",
                "did:hospital:allocation-agent",
            ],
        )

        print(f"[Healthcare] Initialized context: {context_id}")
        self.state["patient_input"] = self.state.get(
            "patient_input", self._default_patient()
        )
        return self.state["patient_input"]

    @listen(init)
    def raw_pipeline(self, input_data):
        """Pipeline 1 (raw_forward): sensor → ontology classification.

        Reads the raw signal and classifies it against a clinical ontology.
        Under raw_forward the full envelope crosses the internal handoff, so
        the classifier sees the raw observations. The terminal artifact (the
        ontology-classified semantic_payload) is returned to feed pipeline 2.
        """
        print("[Healthcare] Pipeline 1/2: Raw-Forward (sensor → ontology)...")

        # Stage-local enforcer + preamble (RAW_FORWARD).
        self.state["_enforcer"] = ForwardingEnforcer(ForwardingPolicy.RAW_FORWARD)
        self.state["_forwarding_preamble"] = ForwardingPolicy.RAW_FORWARD.format_preamble(
            risk_level="high"
        )

        crew_instance = HealthcareRawCrew().crew()
        crew_instance.task_callback = self._persist_task_callback

        result = crew_instance.kickoff(inputs={
            **input_data,
            "_forwarding_preamble": self.state["_forwarding_preamble"],
        })
        return result.raw

    @listen(raw_pipeline)
    def semantic_pipeline(self, raw_terminal):
        """Pipeline 2 (semantic_forward): triage → allocation.

        Consumes the raw pipeline's terminal artifact (the ontology-classified
        semantic_payload) as input; each handoff is filtered to the
        semantic_payload only.
        """
        print("[Healthcare] Pipeline 2/2: Semantic-Forward (triage → allocation)...")

        # Stage-local enforcer + preamble (SEMANTIC_FORWARD).
        self.state["_enforcer"] = ForwardingEnforcer(ForwardingPolicy.SEMANTIC_FORWARD)
        self.state["_forwarding_preamble"] = (
            ForwardingPolicy.SEMANTIC_FORWARD.format_preamble(risk_level="high")
        )

        crew_instance = HealthcareSemanticCrew().crew()
        crew_instance.task_callback = self._persist_task_callback

        result = crew_instance.kickoff(inputs={
            **self.state["patient_input"],
            "upstream_semantic_payload": raw_terminal,
            "_forwarding_preamble": self.state["_forwarding_preamble"],
        })

        # Log the allocation decision
        self._log_decision(
            outcome={"recommendation": result.raw[:200], "requires_oversight": True},
            agent_id="did:hospital:allocation-agent",
        )
        return result.raw

    @listen(semantic_pipeline)
    def physician_oversight(self, decision_output):
        """Step 4: Physician oversight with fine-grained PROV events.

        The flow code controls document-access timing to produce reliable
        PROV activities. The LLM oversight crew produces the narrative
        review/override decision.
        """
        print("[Healthcare] Step 4/5: Physician oversight...")

        # ── Code-controlled document access with real timestamps ──
        oversight_events = []
        overall_t0 = datetime.now(timezone.utc)

        for event_id, label, entity_id, entity_label, duration in SOURCE_DOCUMENTS:
            t0 = datetime.now(timezone.utc)
            _time.sleep(duration)
            t1 = datetime.now(timezone.utc)
            oversight_events.append({
                "event_id": event_id,
                "label": label,
                "started_at": t0.isoformat(),
                "ended_at": t1.isoformat(),
                "accessed_entity": entity_id,
                "entity_label": entity_label,
            })

        # ── LLM crew produces the clinical narrative ──
        result = HealthcareOversightCrew().crew().kickoff(
            inputs={"recommendation": decision_output}
        )
        overall_t1 = datetime.now(timezone.utc)

        # ── Persist fine-grained oversight events to PROV graph ──
        self._persist_oversight_events(
            events=oversight_events,
            oversight_agent_id="did:hospital:dr-chen",
            summary_output=result.raw,
            overall_started_at=overall_t0.isoformat(),
            overall_ended_at=overall_t1.isoformat(),
        )

        # Parse alternatives from LLM output for decision graph
        try:
            oversight_json = json.loads(result.raw)
            alternatives = oversight_json.get("alternatives_considered", [])
            if alternatives:
                self._log_decision(
                    outcome={
                        "decision": oversight_json.get("decision", "unknown"),
                        "justification": oversight_json.get("justification", ""),
                    },
                    agent_id="did:hospital:dr-chen",
                    alternatives=alternatives,
                )
        except (json.JSONDecodeError, AttributeError):
            pass

        return result.raw

    @listen(physician_oversight)
    def compliance_audit(self, oversight_output):
        """Step 5: Programmatic + narrative compliance audit."""
        print("[Healthcare] Step 5/5: Compliance audit...")

        prov = self.state["_prov"]
        builder = self.state["_builder"]

        # ── Programmatic SDK audit ──
        human_activities = [e[0] for e in SOURCE_DOCUMENTS]
        temporal_result = verify_temporal_oversight(
            prov=prov,
            ai_activity_id="act-allocation",
            human_activities=human_activities,
            min_review_seconds=5.0,  # simulated (real: 300.0)
        )

        env = builder.sign("did:hospital:audit-agent").build()
        integrity_result = verify_integrity(env)

        programmatic_report = generate_audit_report(
            env, prov, [temporal_result, integrity_result]
        )

        print(f"[Healthcare] Temporal oversight: {'PASS' if temporal_result.passed else 'FAIL'}")
        print(f"[Healthcare] Integrity: {'PASS' if integrity_result.passed else 'FAIL'}")

        # ── LLM narrative audit ──
        t0 = datetime.now(timezone.utc)
        result = HealthcareAuditCrew().crew().kickoff(
            inputs={
                "oversight_report": oversight_output,
                "context_id": self.state["_context_id"],
            }
        )
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="audit",
            agent_id="did:hospital:audit-agent",
            output=result.raw,
            artifact_type=ArtifactType.TOOL_RESULT,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-oversight", "art-allocation", "art-triage", "art-ontology", "art-sensor"],
        )

        # Save outputs for paper evidence
        self._save_outputs(result.raw, programmatic_report)
        return result.raw

    def _save_outputs(self, audit_output: str, programmatic_report=None):
        """Save envelopes, PROV, audit report, and metrics to output/."""
        context_id = self.state["_context_id"]

        # Per-task envelopes (each task has its own context_id + preamble)
        task_envelopes = self.state.get("_task_envelopes", [])
        (_out.current / "healthcare_envelopes.json").write_text(
            json.dumps(task_envelopes, indent=2)
        )

        # PROV graph
        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "healthcare_prov.ttl").write_text(prov_turtle)

        # Audit report — combined programmatic + narrative
        audit_data = {
            "context_id": context_id,
            "programmatic_checks": programmatic_report.to_dict() if programmatic_report else {},
            "narrative_audit": audit_output,
            "overall_passed": programmatic_report.overall_passed if programmatic_report else None,
        }
        (_out.current / "healthcare_audit.json").write_text(
            json.dumps(audit_data, indent=2)
        )

        # Metrics
        metrics = self._finalize_metrics()
        (_out.current / "healthcare_metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )

        self._cleanup()
        print(f"[Healthcare] Outputs saved to {_out.current}/")

    @staticmethod
    def _default_patient() -> dict:
        return {
            "patient_id": "P-12345",
            "age": "62",
            "gender": "M",
            "lab_results": "Elevated tumor markers (CEA: 12.5 ng/mL), WBC: 7.2, Hgb: 13.1",
            "imaging_metadata": "CT chest/abdomen: 2.3cm pulmonary nodule RUL, decreased from 3.1cm prior",
        }

"""Healthcare Human Oversight Flow — Article 14 EU AI Act.

3-step pipeline: clinical_pipeline (sensor→situation→decision) → oversight → audit.

The clinical pipeline runs as a single multi-task crew (HealthcareClinicalCrew)
with Semantic-Forward task chaining: each task outputs a full jhcontext Envelope,
and subsequent tasks consume the ``semantic_payload`` field as canonical input.

Task-level persistence happens in parallel via ``_persist_task_callback`` —
each task's Envelope is signed and POSTed to the backend while the next task runs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.healthcare.crew import (
    HealthcareAuditCrew,
    HealthcareClinicalCrew,
    HealthcareOversightCrew,
)
from agent.protocol.context_mixin import ContextMixin

from jhcontext import ArtifactType, RiskLevel

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


class HealthcareFlow(Flow, ContextMixin):
    """Healthcare human oversight compliance flow.

    Demonstrates Article 14 compliance by recording the complete
    decision chain from sensor observations through physician review,
    with temporal evidence of meaningful human oversight.
    """

    @start()
    def init(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="healthcare_treatment_recommendation",
            producer="did:hospital:system",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
        )
        print(f"[Healthcare] Initialized context: {context_id}")
        return self.state.get("patient_input", self._default_patient())

    @listen(init)
    def clinical_pipeline(self, input_data):
        """Steps 1-3: sensor → situation → decision (single multi-task crew).

        The HealthcareClinicalCrew runs 3 tasks sequentially. Each task
        outputs a full jhcontext Envelope. The task_callback persists each
        Envelope to the backend in parallel with the next task's execution.
        """
        print("[Healthcare] Steps 1-3: Clinical pipeline (Semantic-Forward)...")

        clinical_crew = HealthcareClinicalCrew()
        crew_instance = clinical_crew.crew()
        crew_instance.task_callback = self._persist_task_callback

        preamble = self.state["_forwarding_preamble"]
        result = crew_instance.kickoff(inputs={
            **input_data,
            "_forwarding_preamble": preamble,
        })

        # Log the treatment decision
        self._log_decision(
            outcome={"recommendation": result.raw[:200], "requires_oversight": True},
            agent_id="did:hospital:decision-agent",
        )
        return result.raw

    @listen(clinical_pipeline)
    def physician_oversight(self, decision_output):
        """Step 4: Physician oversight (separate crew for regulatory isolation)."""
        print("[Healthcare] Step 4/5: Physician oversight...")
        t0 = datetime.now(timezone.utc)
        result = HealthcareOversightCrew().crew().kickoff(
            inputs={"recommendation": decision_output}
        )
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="oversight",
            agent_id="did:hospital:dr-chen",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-decision", "art-sensor"],
        )
        return result.raw

    @listen(physician_oversight)
    def compliance_audit(self, oversight_output):
        """Step 5: Compliance audit (separate crew for regulatory isolation)."""
        print("[Healthcare] Step 5/5: Compliance audit...")
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
            used_artifacts=["art-oversight", "art-decision", "art-situation", "art-sensor"],
        )

        # Save outputs for paper evidence
        self._save_outputs(result.raw)
        return result.raw

    def _save_outputs(self, audit_output: str):
        """Save envelope, PROV, audit report, and metrics to output/."""
        context_id = self.state["_context_id"]
        client = self.state["_api_client"]

        # Envelope
        envelope = client.get_envelope(context_id)
        (OUTPUT_DIR / "healthcare_envelope.json").write_text(
            json.dumps(envelope, indent=2)
        )

        # PROV graph
        prov_turtle = self.state["_prov"].serialize("turtle")
        (OUTPUT_DIR / "healthcare_prov.ttl").write_text(prov_turtle)

        # Audit report
        (OUTPUT_DIR / "healthcare_audit.json").write_text(
            json.dumps({"context_id": context_id, "audit_output": audit_output}, indent=2)
        )

        # Metrics
        metrics = self._finalize_metrics()
        (OUTPUT_DIR / "healthcare_metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )

        self._cleanup()
        print(f"[Healthcare] Outputs saved to {OUTPUT_DIR}/")

    @staticmethod
    def _default_patient() -> dict:
        return {
            "patient_id": "P-12345",
            "age": "62",
            "gender": "M",
            "lab_results": "Elevated tumor markers (CEA: 12.5 ng/mL), WBC: 7.2, Hgb: 13.1",
            "imaging_metadata": "CT chest/abdomen: 2.3cm pulmonary nodule RUL, decreased from 3.1cm prior",
        }

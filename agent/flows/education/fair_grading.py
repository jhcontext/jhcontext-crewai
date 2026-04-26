"""Fair Grading Flow — EU AI Act Art. 13 non-discrimination.

Education-domain scenario demonstrating Article 13 compliance through:
- a two-agent grading pipeline (ingestion → grading) that touches zero
  identity data;
- an isolated equity-reporting pipeline that touches zero grading data;
- a cross-workflow audit that proves the two pipelines share no artifacts
  (workflow isolation + negative proof).

For the richer rubric-grounded feedback variant (6-agent pipeline with
per-sentence feedback envelopes + TA review), see the sibling module
``agent/flows/education/rubric_feedback_grading.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.education.fair_grading.crew import (
    EducationAuditCrew,
    EducationEquityCrew,
    EducationGradingCrew,
    EducationIngestionCrew,
)
from agent.protocol.context_mixin import ContextMixin

from jhcontext import ArtifactType, PROVGraph, RiskLevel

import agent.output_dir as _out


class EducationGradingFlow(Flow, ContextMixin):
    """Grading workflow — isolated from identity data.

    Demonstrates Article 13 compliance via negative provenance proof:
    the grading chain contains zero identity artifacts.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_assessment_grading",
            producer="did:university:grading-system",
            risk_level=RiskLevel.HIGH,
            human_oversight=False,
            feature_suppression=[
                "student_name", "student_id",
                "accommodation_flags", "prior_grades",
            ],
        )

        self._register_crew(
            crew_id="crew:grading",
            label="Grading Crew",
            agent_ids=[
                "did:university:ingestion-agent",
                "did:university:grading-agent",
            ],
        )

        print(f"[Education/Grading] Initialized context: {context_id}")
        return self.state.get("submission_input", self._default_submission())

    @listen(init)
    def essay_ingestion(self, input_data):
        print("[Education/Grading] Step 1/3: Essay ingestion (identity separation)...")
        t0 = datetime.now(timezone.utc)
        result = EducationIngestionCrew().crew().kickoff(inputs=input_data)
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="ingestion",
            agent_id="did:university:ingestion-agent",
            output=result.raw,
            artifact_type=ArtifactType.TOKEN_SEQUENCE,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
        )
        return result.raw

    @listen(essay_ingestion)
    def blind_grading(self, essay_text):
        print("[Education/Grading] Step 2/3: Blind grading...")
        t0 = datetime.now(timezone.utc)
        result = EducationGradingCrew().crew().kickoff(
            inputs={"essay_text": essay_text}
        )
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="grading",
            agent_id="did:university:grading-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-ingestion"],
        )

        self._log_decision(
            outcome={"grade": result.raw[:100]},
            agent_id="did:university:grading-agent",
        )
        return result.raw

    @listen(blind_grading)
    def grading_complete(self, grading_output):
        """Save grading workflow outputs."""
        # Per-task envelopes
        task_envelopes = self.state.get("_task_envelopes", [])
        (_out.current / "education_grading_envelopes.json").write_text(
            json.dumps(task_envelopes, indent=2)
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "education_grading_prov.ttl").write_text(prov_turtle)

        metrics = self._finalize_metrics()
        (_out.current / "education_grading_metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )

        self._cleanup()
        print(f"[Education/Grading] Outputs saved to {_out.current}/")
        return grading_output

    @staticmethod
    def _default_submission() -> dict:
        return {
            "student_id": "S-98765",
            "essay_topic": "The Role of Carbon Pricing in Climate Policy",
            "word_count": "1500",
        }


class EducationEquityFlow(Flow, ContextMixin):
    """Equity reporting workflow — completely isolated from grading."""

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_equity_reporting",
            producer="did:university:equity-system",
            risk_level=RiskLevel.MEDIUM,
            human_oversight=False,
        )

        self._register_crew(
            crew_id="crew:equity",
            label="Equity Crew",
            agent_ids=["did:university:equity-agent"],
        )

        print(f"[Education/Equity] Initialized context: {context_id}")
        return self.state.get("identity_input", self._default_identity())

    @listen(init)
    def equity_reporting(self, identity_data):
        print("[Education/Equity] Generating equity report...")
        t0 = datetime.now(timezone.utc)
        result = EducationEquityCrew().crew().kickoff(inputs=identity_data)
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="equity",
            agent_id="did:university:equity-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "education_equity_prov.ttl").write_text(prov_turtle)

        self._cleanup()
        print(f"[Education/Equity] Outputs saved to {_out.current}/")
        return result.raw

    @staticmethod
    def _default_identity() -> dict:
        return {
            "aggregate_demographics": "Class of 120 students: 52% female, 48% male; 35% first-generation",
        }


class EducationAuditFlow(Flow):
    """Audit workflow — verifies isolation between grading and equity."""

    @start()
    def init(self):
        return self.state.get("audit_input", {})

    @listen(init)
    def run_audit(self, audit_input):
        print("[Education/Audit] Verifying workflow isolation...")

        # Load both PROV graphs
        grading_prov_path = _out.current / "education_grading_prov.ttl"
        equity_prov_path = _out.current / "education_equity_prov.ttl"

        if not grading_prov_path.exists() or not equity_prov_path.exists():
            print("[Education/Audit] ERROR: Run grading and equity flows first.")
            return {"error": "Missing PROV graphs"}

        # Use jhcontext audit to verify isolation + negative proof
        from jhcontext.audit import (
            verify_negative_proof,
            verify_workflow_isolation,
        )

        prov_a = PROVGraph(context_id="grading")
        prov_a._graph.parse(data=grading_prov_path.read_text(), format="turtle")

        prov_b = PROVGraph(context_id="equity")
        prov_b._graph.parse(data=equity_prov_path.read_text(), format="turtle")

        # SDK audit: workflow isolation (zero shared artifacts)
        isolation_result = verify_workflow_isolation(prov_a, prov_b)

        # SDK audit: negative proof (identity artifacts absent from grading)
        negative_result = verify_negative_proof(
            prov=prov_a,
            decision_entity_id="art-grading",
            excluded_artifact_types=["identity_data", "demographic", "biometric"],
        )

        print(f"[Education/Audit] Workflow isolation: {'PASS' if isolation_result.passed else 'FAIL'}")
        print(f"[Education/Audit] Negative proof: {'PASS' if negative_result.passed else 'FAIL'}")

        # Run CrewAI audit agent for narrative report
        t0 = datetime.now(timezone.utc)
        result = EducationAuditCrew().crew().kickoff(
            inputs={
                "isolation_passed": str(isolation_result.passed),
                "isolation_evidence": json.dumps(isolation_result.evidence),
                "negative_proof_passed": str(negative_result.passed),
                "negative_proof_evidence": json.dumps(negative_result.evidence),
            }
        )
        t1 = datetime.now(timezone.utc)

        report = {
            "workflow_isolation": {
                "passed": isolation_result.passed,
                "evidence": isolation_result.evidence,
                "message": isolation_result.message,
            },
            "negative_proof": {
                "passed": negative_result.passed,
                "evidence": negative_result.evidence,
                "message": negative_result.message,
            },
            "audit_narrative": result.raw,
            "verified_at": t1.isoformat(),
            "overall_passed": isolation_result.passed and negative_result.passed,
        }

        (_out.current / "education_audit.json").write_text(json.dumps(report, indent=2))
        print(f"[Education/Audit] Overall: {'PASSED' if report['overall_passed'] else 'FAILED'}")
        print(f"[Education/Audit] Report saved to {_out.current}/education_audit.json")
        return report

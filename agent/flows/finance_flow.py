"""Financial Credit Assessment Flow — EU AI Act Annex III 5(b), Articles 13/14.

Composite compliance scenario combining ALL 4 PAC-AI patterns:
  1. Negative proof (Art. 13) — protected attributes absent from credit decision
  2. Temporal oversight (Art. 14) — credit officer reviews source documents
  3. Workflow isolation — fair lending analysis separated from credit scoring
  4. PII detachment (GDPR) — financial identifiers tokenized

Three independent flows:
  - FinanceCreditFlow: data_collection → risk_analysis → credit_decision → oversight → audit
  - FinanceFairLendingFlow: aggregate demographics → fair lending report
  - FinanceAuditFlow: cross-workflow verification (isolation + negative proof)
"""

from __future__ import annotations

import json
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.finance.crew import (
    FinanceAuditCrew,
    FinanceCreditCrew,
    FinanceFairLendingCrew,
    FinanceOversightCrew,
)
from agent.protocol.context_mixin import ContextMixin

from jhcontext import ArtifactType, PROVGraph, RiskLevel
from jhcontext.audit import (
    generate_audit_report,
    verify_integrity,
    verify_negative_proof,
    verify_temporal_oversight,
    verify_workflow_isolation,
)

import agent.output_dir as _out

# Simulated document-access durations (seconds).
# Production would use real credit officer interaction times.
SOURCE_DOCUMENTS = [
    ("act-access-income", "Access income verification", "ent-income-docs", "Income verification documents", 3),
    ("act-access-employment", "Access employment records", "ent-employment-records", "Employment records", 2),
    ("act-access-bureau", "Access credit bureau report", "ent-bureau-report", "Credit bureau report", 3),
    ("act-review-ai", "Review AI credit recommendation", "ent-ai-recommendation", "AI credit recommendation", 2),
]


class FinanceCreditFlow(Flow, ContextMixin):
    """Credit assessment flow with human oversight.

    Demonstrates composite compliance: Semantic-Forward pipeline with
    negative proof (no protected attributes), temporal oversight (credit
    officer review), PII detachment (financial identifiers tokenized),
    and explainable decisions (Art. 13 + GDPR Art. 22).
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="credit_assessment",
            producer="did:bank:credit-system",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
            feature_suppression=["applicant_name", "tax_id", "account_number", "address"],
        )

        # Register the credit pipeline crew in the PROV graph.
        # The credit officer is intentionally outside the crew —
        # oversight must be external to the automated pipeline.
        self._register_crew(
            crew_id="crew:credit-pipeline",
            label="Credit Assessment Pipeline Crew",
            agent_ids=[
                "did:bank:data-collector-agent",
                "did:bank:risk-analyzer-agent",
                "did:bank:decision-agent",
            ],
        )

        print(f"[Finance/Credit] Initialized context: {context_id}")
        return self.state.get("application_input", self._default_application())

    @listen(init)
    def credit_pipeline(self, input_data):
        """Steps 1-3: data_collection → risk_analysis → credit_decision.

        The FinanceCreditCrew runs 3 tasks sequentially. Each task
        outputs a full jhcontext Envelope. The task_callback persists each
        Envelope to the backend in parallel with the next task's execution.
        """
        print("[Finance/Credit] Steps 1-3: Credit pipeline (Semantic-Forward)...")

        credit_crew = FinanceCreditCrew()
        crew_instance = credit_crew.crew()
        crew_instance.task_callback = self._persist_task_callback

        preamble = self.state["_forwarding_preamble"]
        result = crew_instance.kickoff(inputs={
            **input_data,
            "_forwarding_preamble": preamble,
        })

        # Log the credit decision
        self._log_decision(
            outcome={"recommendation": result.raw[:200], "requires_oversight": True},
            agent_id="did:bank:decision-agent",
        )
        return result.raw

    @listen(credit_pipeline)
    def officer_oversight(self, decision_output):
        """Step 4: Credit officer oversight with fine-grained PROV events.

        The flow code controls document-access timing to produce reliable
        PROV activities. The LLM oversight crew produces the narrative
        review/override decision.
        """
        print("[Finance/Credit] Step 4/5: Credit officer oversight...")

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

        # ── LLM crew produces the officer narrative ──
        result = FinanceOversightCrew().crew().kickoff(
            inputs={"recommendation": decision_output}
        )
        overall_t1 = datetime.now(timezone.utc)

        # ── Persist fine-grained oversight events to PROV graph ──
        self._persist_oversight_events(
            events=oversight_events,
            oversight_agent_id="did:bank:credit-officer",
            summary_output=result.raw,
            overall_started_at=overall_t0.isoformat(),
            overall_ended_at=overall_t1.isoformat(),
        )

        # Parse decision from LLM output for decision graph
        try:
            oversight_json = json.loads(result.raw)
            conditions = oversight_json.get("conditions_modified", [])
            if conditions or oversight_json.get("decision") != "approve":
                self._log_decision(
                    outcome={
                        "decision": oversight_json.get("decision", "unknown"),
                        "justification": oversight_json.get("justification", ""),
                    },
                    agent_id="did:bank:credit-officer",
                    alternatives=[{"option": "original_ai_recommendation"}] if conditions else [],
                )
        except (json.JSONDecodeError, AttributeError):
            pass

        return result.raw

    @listen(officer_oversight)
    def compliance_audit(self, oversight_output):
        """Step 5: Programmatic + narrative compliance audit."""
        print("[Finance/Credit] Step 5/5: Compliance audit...")

        prov = self.state["_prov"]
        builder = self.state["_builder"]

        # ── Programmatic SDK audit ──
        human_activities = [e[0] for e in SOURCE_DOCUMENTS]
        temporal_result = verify_temporal_oversight(
            prov=prov,
            ai_activity_id="act-credit-decision",
            human_activities=human_activities,
            min_review_seconds=5.0,  # simulated (real: 300.0)
        )

        # Negative proof: protected attributes absent from decision chain
        negative_result = verify_negative_proof(
            prov=prov,
            decision_entity_id="art-credit-decision",
            excluded_artifact_types=["gender", "ethnicity", "marital_status", "nationality", "age", "religion"],
        )

        env = builder.sign("did:bank:audit-agent").build()
        integrity_result = verify_integrity(env)

        programmatic_report = generate_audit_report(
            env, prov, [temporal_result, negative_result, integrity_result]
        )

        print(f"[Finance/Credit] Temporal oversight: {'PASS' if temporal_result.passed else 'FAIL'}")
        print(f"[Finance/Credit] Negative proof: {'PASS' if negative_result.passed else 'FAIL'}")
        print(f"[Finance/Credit] Integrity: {'PASS' if integrity_result.passed else 'FAIL'}")

        # ── LLM narrative audit ──
        t0 = datetime.now(timezone.utc)
        result = FinanceAuditCrew().crew().kickoff(
            inputs={
                "negative_proof_passed": str(negative_result.passed),
                "negative_proof_evidence": json.dumps(negative_result.evidence),
                "temporal_oversight_passed": str(temporal_result.passed),
                "temporal_oversight_evidence": json.dumps(temporal_result.evidence),
                "isolation_passed": "pending",  # will be verified in FinanceAuditFlow
                "isolation_evidence": "{}",
                "integrity_passed": str(integrity_result.passed),
            }
        )
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="audit",
            agent_id="did:bank:audit-agent",
            output=result.raw,
            artifact_type=ArtifactType.TOOL_RESULT,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-oversight", "art-credit-decision", "art-risk-analysis", "art-financial-data"],
        )

        # Save outputs
        self._save_outputs(result.raw, programmatic_report)
        return result.raw

    def _save_outputs(self, audit_output: str, programmatic_report=None):
        """Save envelopes, PROV, audit report, and metrics to output/."""
        context_id = self.state["_context_id"]

        # Per-task envelopes
        task_envelopes = self.state.get("_task_envelopes", [])
        (_out.current / "finance_envelopes.json").write_text(
            json.dumps(task_envelopes, indent=2)
        )

        # PROV graph
        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "finance_credit_prov.ttl").write_text(prov_turtle)

        # Audit report — combined programmatic + narrative
        audit_data = {
            "context_id": context_id,
            "programmatic_checks": programmatic_report.to_dict() if programmatic_report else {},
            "narrative_audit": audit_output,
            "overall_passed": programmatic_report.overall_passed if programmatic_report else None,
        }
        (_out.current / "finance_audit.json").write_text(
            json.dumps(audit_data, indent=2)
        )

        # Metrics
        metrics = self._finalize_metrics()
        (_out.current / "finance_metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )

        self._cleanup()
        print(f"[Finance/Credit] Outputs saved to {_out.current}/")

    @staticmethod
    def _default_application() -> dict:
        return {
            "applicant_id": "APP-2026-00847",
            "requested_amount": "25000",
            "currency": "EUR",
            "loan_purpose": "home_renovation",
            "monthly_income": "3800",
            "employment_type": "permanent_contract",
            "employer_tenure_months": "48",
            "existing_monthly_debt": "420",
            "credit_bureau_score": "710",
            "payment_history_ontime_pct": "96",
            "collateral_type": "none",
        }


class FinanceFairLendingFlow(Flow, ContextMixin):
    """Fair lending reporting workflow — completely isolated from credit assessment."""

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="fair_lending_reporting",
            producer="did:bank:fair-lending-system",
            risk_level=RiskLevel.MEDIUM,
            human_oversight=False,
        )

        self._register_crew(
            crew_id="crew:fair-lending",
            label="Fair Lending Crew",
            agent_ids=["did:bank:fair-lending-agent"],
        )

        print(f"[Finance/FairLending] Initialized context: {context_id}")
        return self.state.get("demographics_input", self._default_demographics())

    @listen(init)
    def fair_lending_report(self, demographics_data):
        print("[Finance/FairLending] Generating fair lending report...")
        t0 = datetime.now(timezone.utc)
        result = FinanceFairLendingCrew().crew().kickoff(inputs=demographics_data)
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="fair_lending",
            agent_id="did:bank:fair-lending-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "finance_fair_lending_prov.ttl").write_text(prov_turtle)

        self._cleanup()
        print(f"[Finance/FairLending] Outputs saved to {_out.current}/")
        return result.raw

    @staticmethod
    def _default_demographics() -> dict:
        return {
            "aggregate_demographics": (
                "Q1 2026 loan applications (n=1,247): "
                "52% male, 48% female; "
                "age distribution: 18-30 (25%), 31-45 (42%), 46-60 (28%), 60+ (5%); "
                "nationality: 78% domestic, 22% EU/EEA; "
                "approval rate overall: 68%; "
                "average requested amount: EUR 18,500"
            ),
        }


class FinanceAuditFlow(Flow):
    """Audit workflow — verifies isolation between credit and fair lending workflows."""

    @start()
    def init(self):
        return self.state.get("audit_input", {})

    @listen(init)
    def run_audit(self, audit_input):
        print("[Finance/Audit] Verifying workflow isolation...")

        # Load both PROV graphs
        credit_prov_path = _out.current / "finance_credit_prov.ttl"
        fair_lending_prov_path = _out.current / "finance_fair_lending_prov.ttl"

        if not credit_prov_path.exists() or not fair_lending_prov_path.exists():
            print("[Finance/Audit] ERROR: Run credit and fair lending flows first.")
            return {"error": "Missing PROV graphs"}

        prov_credit = PROVGraph(context_id="credit")
        prov_credit._graph.parse(data=credit_prov_path.read_text(), format="turtle")

        prov_fair = PROVGraph(context_id="fair_lending")
        prov_fair._graph.parse(data=fair_lending_prov_path.read_text(), format="turtle")

        # SDK audit: workflow isolation (zero shared artifacts)
        isolation_result = verify_workflow_isolation(prov_credit, prov_fair)

        # SDK audit: negative proof (protected attributes absent from credit decision)
        negative_result = verify_negative_proof(
            prov=prov_credit,
            decision_entity_id="art-credit-decision",
            excluded_artifact_types=["gender", "ethnicity", "marital_status", "nationality", "age", "religion"],
        )

        print(f"[Finance/Audit] Workflow isolation: {'PASS' if isolation_result.passed else 'FAIL'}")
        print(f"[Finance/Audit] Negative proof: {'PASS' if negative_result.passed else 'FAIL'}")

        # Load and update per-flow audit report with isolation results
        audit_path = _out.current / "finance_audit.json"
        if audit_path.exists():
            audit_data = json.loads(audit_path.read_text())
        else:
            audit_data = {}

        report = {
            **audit_data,
            "workflow_isolation": {
                "passed": isolation_result.passed,
                "evidence": isolation_result.evidence,
                "message": isolation_result.message,
            },
            "cross_workflow_negative_proof": {
                "passed": negative_result.passed,
                "evidence": negative_result.evidence,
                "message": negative_result.message,
            },
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "composite_compliance": {
                "patterns_verified": [
                    "negative_proof",
                    "temporal_oversight",
                    "workflow_isolation",
                    "integrity",
                ],
                "all_passed": (
                    isolation_result.passed
                    and negative_result.passed
                    and audit_data.get("overall_passed", False)
                ),
            },
        }

        (_out.current / "finance_audit.json").write_text(json.dumps(report, indent=2))
        overall = report["composite_compliance"]["all_passed"]
        print(f"[Finance/Audit] Composite compliance: {'PASSED' if overall else 'FAILED'}")
        print(f"[Finance/Audit] Report saved to {_out.current}/finance_audit.json")
        return report

"""Rubric-Grounded Grading Flows — three scenarios on a shared 6-agent pipeline.

Auditable AI assessment: provenance-aware evaluation and rubric-grounded
feedback for student work. Three scenarios exercise the same pipeline:

  A. Identity-blind essay grading (negative proof + workflow isolation).
  B. Rubric-grounded LLM feedback (per-sentence traceability to a rubric
     criterion, an evidence span, a model version, and a prompt-template
     hash).
  C. Human-AI collaborative grading (TA review with temporal oversight).

Flows:
  * ``RubricGradingFlow``   — 3-agent pipeline
                              (ingestion → criterion-scoring →
                               feedback with per-sentence envelopes)
  * ``RubricEquityFlow``    — isolated equity workflow
                              (feeds Scenario A's workflow-isolation
                               verifier)
  * ``RubricTAReviewFlow``  — TA review with fine-grained document-
                              access PROV events (Scenario C
                              temporal oversight)
  * ``RubricAuditFlow``     — runs three SDK verifiers and a
                              narrative audit crew

Output filenames (written to ``_out.current/``):
  education_rubric_grading_envelope.json    flow-level envelope
  education_rubric_envelopes.json           per-task + per-feedback-sentence envelopes
  education_rubric_prov.ttl                 grading pipeline PROV
  education_rubric_metrics.json             timing metrics
  education_rubric_equity_prov.ttl          isolated equity PROV
  education_rubric_ta_review_prov.ttl       TA review PROV (w/ fine-grained events)
  education_rubric_audit.json               three-scenario audit report

For the lighter-weight fairness-only variant (2-agent pipeline + equity +
audit), see the sibling module ``agent/flows/education/fair_grading.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.education.rubric_feedback_grading.crew import (
    RubricAuditCrew,
    RubricCriterionScoringCrew,
    RubricEquityCrew,
    RubricFeedbackCrew,
    RubricIngestionCrew,
    RubricTAReviewCrew,
)
from agent.protocol.context_mixin import ContextMixin

from jhcontext import ArtifactType, PROVGraph, RiskLevel
from jhcontext.audit import (
    generate_audit_report,
    verify_integrity,
    verify_negative_proof,
    verify_rubric_grounding,
    verify_temporal_oversight,
    verify_workflow_isolation,
)

import agent.output_dir as _out


RUBRIC_ID = "rubric_v2.3"
MODEL_ID = "claude-sonnet-4-6"
PROMPT_TEMPLATE_ID = "rubric_fb_per_criterion_v1"
PROMPT_TEMPLATE_HASH = "sha256:" + hashlib.sha256(PROMPT_TEMPLATE_ID.encode()).hexdigest()[:16] + "..."


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json_array(text: str) -> list[dict]:
    """Best-effort extraction of a JSON array from an LLM-generated string.

    CrewAI task outputs often wrap JSON in prose or markdown fences. Try:
      1. Direct json.loads(text)
      2. First ```json ... ``` fenced block
      3. Regex for first ``[`` ... ``]`` balanced block
      4. Fallback: empty list
    """
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        pass
    # Try fenced block
    fence = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # First bracketed array
    m = re.search(r"(\[[\s\S]*\])", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return []


# =============================================================================
# Scenario A + B shared pipeline — grading flow
# =============================================================================

class RubricGradingFlow(Flow, ContextMixin):
    """Rubric 3-agent pipeline: ingestion → criterion-scoring → feedback.

    Emits one PAC-AI envelope for the flow, one per-task envelope for each of
    the three stages, and **one additional envelope per LLM-generated
    feedback sentence** during the feedback stage. Per-sentence envelopes
    carry ``rubricCriterionId`` + ``evidenceSpanHash`` + ``modelVersion`` +
    ``promptTemplateHash`` attributes that ``verify_rubric_grounding`` will
    later audit.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_rubric_assessment",
            producer="did:university:grading-system-rubric",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
            feature_suppression=[
                "student_name", "student_id",
                "accommodation_flags", "prior_grades",
            ],
        )

        self._register_crew(
            crew_id="crew:rubric-grading",
            label="Rubric Grading Crew",
            agent_ids=[
                "did:university:rubric-ingestion-agent",
                "did:university:rubric-criterion-scoring-agent",
                "did:university:rubric-feedback-agent",
            ],
        )

        print(f"[Rubric/Grading] Initialized context: {context_id}")
        return self.state.get("submission_input", self._default_submission())

    @listen(init)
    def essay_ingestion(self, input_data):
        print("[Rubric/Grading] Step 1/3: Essay ingestion (identity separation)...")
        t0 = datetime.now(timezone.utc)
        result = RubricIngestionCrew().crew().kickoff(inputs=input_data)
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="ingestion",
            agent_id="did:university:rubric-ingestion-agent",
            output=result.raw,
            artifact_type=ArtifactType.TOKEN_SEQUENCE,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
        )

        self.state["_ingestion_output"] = result.raw
        self.state["_essay_text"] = input_data.get("essay_text", result.raw)
        return result.raw

    @listen(essay_ingestion)
    def criterion_scoring(self, essay_text):
        print("[Rubric/Grading] Step 2/3: Per-criterion scoring...")
        t0 = datetime.now(timezone.utc)
        result = RubricCriterionScoringCrew().crew().kickoff(
            inputs={"essay_text": essay_text}
        )
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="scoring",
            agent_id="did:university:rubric-criterion-scoring-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-ingestion"],
        )

        self._log_decision(
            outcome={"aggregate_score": result.raw[:100]},
            agent_id="did:university:rubric-criterion-scoring-agent",
        )
        self.state["_scoring_output"] = result.raw
        return result.raw

    @listen(criterion_scoring)
    def feedback_generation(self, scoring_output):
        """Generate 6-10 feedback sentences and emit one envelope per sentence.

        This is Scenario B's load-bearing step: each sentence is bound to a
        rubric criterion, an evidence span, a model version, and a prompt-
        template hash via attributes on the PROV entity.
        """
        print("[Rubric/Grading] Step 3/3: Rubric-grounded feedback generation...")
        t0 = datetime.now(timezone.utc)
        result = RubricFeedbackCrew().crew().kickoff(
            inputs={
                "scoring_output": scoring_output,
                "essay_text": self.state.get("_essay_text", ""),
                "rubric_id": RUBRIC_ID,
                "model_id": MODEL_ID,
                "prompt_template_hash": PROMPT_TEMPLATE_HASH,
            }
        )
        t1 = datetime.now(timezone.utc)

        # Parse feedback sentences from LLM output; fall back to an empty list
        sentences = _extract_json_array(result.raw)
        self.state["_feedback_sentences"] = sentences

        # Record the feedback-generation handoff as ONE aggregate step.
        # This emits a single PAC-AI envelope for the whole feedback block
        # (per the protocol spec: one envelope per handoff). Per-sentence
        # information lives in the envelope's UserML interpretation layer,
        # and per-sentence PROV entities below preserve audit granularity.
        self._persist_step(
            step_name="feedback",
            agent_id="did:university:rubric-feedback-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-scoring", "art-ingestion"],
        )

        # Per-sentence PROV entities — the verifier (verify_rubric_grounding)
        # still inspects these entity attributes; envelope count is unchanged.
        prov: PROVGraph = self.state["_prov"]
        essay_text = self.state.get("_essay_text", "")
        feedback_activity_id = "act-feedback"  # activity created by _persist_step above

        feedback_sentence_ids = []
        for i, fs in enumerate(sentences, start=1):
            fs_id = fs.get("sentence_id") or f"fb-{i:02d}"
            art_id = f"art-feedback-{fs_id}"
            span = fs.get("evidence_span") or {}
            offset = span.get("offset")
            length = span.get("length")
            # Compute the real evidence-span hash if the span exists in the submission
            ev_hash = ""
            if isinstance(offset, int) and isinstance(length, int) and essay_text:
                cited = essay_text[offset:offset + length]
                if cited:
                    ev_hash = "sha256:" + hashlib.sha256(cited.encode()).hexdigest()[:16] + "..."
            criterion_id = fs.get("rubric_criterion_id") or f"{RUBRIC_ID}#unknown"
            fs_text_hash = "sha256:" + hashlib.sha256(
                json.dumps(fs, ensure_ascii=False).encode()
            ).hexdigest()[:16] + "..."

            # Add the sentence as its own PROV entity (generated by the SAME
            # feedback activity as its siblings; no new envelope emitted).
            prov.add_entity(
                art_id,
                f"Feedback sentence {fs_id} assessing {criterion_id}",
                artifact_type="semantic_extraction",
                content_hash=fs_text_hash,
            )
            prov.was_generated_by(art_id, feedback_activity_id)
            prov.was_derived_from(art_id, "art-ingestion")

            # Attach rubric-binding attributes so verify_rubric_grounding
            # can audit them later.
            prov.set_entity_attribute(art_id, "rubricCriterionId", criterion_id)
            prov.set_entity_attribute(art_id, "modelVersion", fs.get("model_version", MODEL_ID))
            prov.set_entity_attribute(
                art_id, "promptTemplateHash",
                fs.get("prompt_template_hash", PROMPT_TEMPLATE_HASH),
            )
            if ev_hash:
                prov.set_entity_attribute(art_id, "evidenceSpanHash", ev_hash)
                if isinstance(offset, int):
                    prov.set_entity_attribute(art_id, "evidenceSpanOffset", offset)
                if isinstance(length, int):
                    prov.set_entity_attribute(art_id, "evidenceSpanLength", length)
            feedback_sentence_ids.append(art_id)

        self.state["_feedback_sentence_ids"] = feedback_sentence_ids
        return result.raw

    @listen(feedback_generation)
    def grading_complete(self, feedback_output):
        task_envelopes = self.state.get("_task_envelopes", [])
        (_out.current / "education_rubric_envelopes.json").write_text(
            json.dumps(task_envelopes, indent=2)
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "education_rubric_prov.ttl").write_text(prov_turtle)

        # Save the per-sentence index for the audit flow
        (_out.current / "education_rubric_feedback_sentences.json").write_text(
            json.dumps({
                "feedback_sentence_ids": self.state.get("_feedback_sentence_ids", []),
                "feedback_sentences": self.state.get("_feedback_sentences", []),
                "context_id": self.state["_context_id"],
                "submission_entity_id": "art-ingestion",
            }, indent=2, ensure_ascii=False)
        )

        metrics = self._finalize_metrics()
        (_out.current / "education_rubric_metrics.json").write_text(json.dumps(metrics, indent=2))

        self._cleanup()
        print(f"[Rubric/Grading] {len(self.state.get('_feedback_sentence_ids', []))} "
              f"per-sentence envelopes emitted; outputs in {_out.current}/")
        return feedback_output

    @staticmethod
    def _default_submission() -> dict:
        return {
            "student_id": "S-98765",
            "essay_topic": "The Role of Carbon Pricing in Climate Policy",
            "word_count": "1527",
            "essay_text": (
                "Climate policy in the twenty-first century must reconcile economic growth "
                "with ecological limits. Carbon pricing, though politically difficult, has "
                "proved effective in jurisdictions that have adopted it. Recent data from "
                "British Columbia shows that a revenue-neutral carbon tax reduced emissions "
                "by 9% between 2008 and 2012 without dampening provincial GDP growth. "
                "However, critics note that equity effects have been mixed, with low-income "
                "households bearing a disproportionate share of the cost in the programme's "
                "first two years. A well-designed rebate mechanism can mitigate this."
            ),
        }


# =============================================================================
# Scenario A — isolated equity workflow
# =============================================================================

class RubricEquityFlow(Flow, ContextMixin):
    """Rubric equity reporting workflow — isolated from the grading pipeline.

    Clone of the ``EducationEquityFlow`` with Rubric-specific output
    filenames. Produces ``education_rubric_equity_prov.ttl`` that the audit
    flow uses for ``verify_workflow_isolation``.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_rubric_equity_reporting",
            producer="did:university:equity-system-rubric",
            risk_level=RiskLevel.MEDIUM,
            human_oversight=False,
        )

        self._register_crew(
            crew_id="crew:rubric-equity",
            label="Rubric Equity Crew",
            agent_ids=["did:university:rubric-equity-agent"],
        )

        print(f"[Rubric/Equity] Initialized context: {context_id}")
        return self.state.get("identity_input", self._default_identity())

    @listen(init)
    def equity_reporting(self, identity_data):
        print("[Rubric/Equity] Generating equity report (isolated workflow)...")
        t0 = datetime.now(timezone.utc)
        result = RubricEquityCrew().crew().kickoff(inputs=identity_data)
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="equity",
            agent_id="did:university:rubric-equity-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "education_rubric_equity_prov.ttl").write_text(prov_turtle)

        self._cleanup()
        print(f"[Rubric/Equity] Outputs saved to {_out.current}/")
        return result.raw

    @staticmethod
    def _default_identity() -> dict:
        return {
            "aggregate_demographics": (
                "Class of 120 students: 52% female, 48% male; 35% first-generation; "
                "18% with disability accommodations."
            ),
        }


# =============================================================================
# Scenario C — TA review with temporal oversight
# =============================================================================

# Simulated document-access durations (seconds). Production TA sessions would
# use real interaction timings captured by the grading platform.
SOURCE_DOCUMENTS = [
    ("act-ta-open-submission",   "TA opens student submission",  "art-ta-submission",  "Student submission",  3),
    ("act-ta-open-rubric",       "TA opens rubric",              "art-ta-rubric",      "Rubric (rubric_v2.3)", 2),
    ("act-ta-open-ai-score",     "TA opens AI aggregate score",  "art-ta-ai-score",    "AI aggregate score",   2),
    ("act-ta-open-ai-feedback",  "TA opens AI feedback block",   "art-ta-ai-feedback", "AI feedback block",    4),
]


class RubricTAReviewFlow(Flow, ContextMixin):
    """Rubric Scenario C — teaching-assistant review with temporal oversight.

    Direct port of ``HealthcareFlow.physician_oversight`` (see
    ``agent/flows/healthcare_flow.py``) with education vocabulary. Records
    four fine-grained document-access activities in the PROV graph with
    real timestamps, then runs the TA-review LLM crew to produce the
    narrative override decision.

    The flow's PROV graph includes a stub "act-ai-feedback" activity
    representing the AI feedback-generation step (timestamped earlier than
    the TA activities) so ``verify_temporal_oversight`` has both sides of
    the relation in a single graph.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_rubric_ta_review",
            producer="did:university:ta-review-system-rubric",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
            feature_suppression=[
                "student_name", "student_id",
                "accommodation_flags", "prior_grades",
            ],
        )

        self._register_crew(
            crew_id="crew:rubric-ta-review",
            label="Rubric TA Review Crew",
            agent_ids=[
                "did:university:rubric-ai-feedback-agent",
                "did:university:rubric-ta-martins",
            ],
        )

        print(f"[Rubric/TA-Review] Initialized context: {context_id}")
        return self.state.get("ta_review_input", self._default_ta_input())

    @listen(init)
    def record_ai_output(self, ta_input):
        """Record the AI feedback activity as a PROV event that the TA review
        will be compared against.
        """
        prov: PROVGraph = self.state["_prov"]
        t_ai = datetime.now(timezone.utc)
        prov.add_activity(
            "act-ai-feedback",
            "AI feedback generation (reference activity for temporal comparison)",
            started_at=t_ai.isoformat(),
            ended_at=t_ai.isoformat(),
        )
        prov.add_agent(
            "did:university:rubric-ai-feedback-agent",
            "AI Feedback Agent",
            role="evaluator",
        )
        prov.was_associated_with("act-ai-feedback", "did:university:rubric-ai-feedback-agent")
        self.state["_ai_activity_ts"] = t_ai.isoformat()
        return ta_input

    @listen(record_ai_output)
    def ta_review(self, ta_input):
        """Step 2: TA review with fine-grained PROV events (per doc access)."""
        print("[Rubric/TA-Review] TA review with document-access events...")

        oversight_events = []
        overall_t0 = datetime.now(timezone.utc)

        for event_id, label, entity_id, entity_label, duration in SOURCE_DOCUMENTS:
            t0 = datetime.now(timezone.utc)
            _time.sleep(duration)  # simulated review time
            t1 = datetime.now(timezone.utc)
            oversight_events.append({
                "event_id": event_id,
                "label": label,
                "started_at": t0.isoformat(),
                "ended_at": t1.isoformat(),
                "accessed_entity": entity_id,
                "entity_label": entity_label,
            })

        result = RubricTAReviewCrew().crew().kickoff(inputs=ta_input)
        overall_t1 = datetime.now(timezone.utc)

        self._persist_oversight_events(
            events=oversight_events,
            oversight_agent_id="did:university:rubric-ta-martins",
            summary_output=result.raw,
            overall_started_at=overall_t0.isoformat(),
            overall_ended_at=overall_t1.isoformat(),
        )

        # Parse the TA review JSON (best effort)
        try:
            ta_json = json.loads(result.raw)
        except json.JSONDecodeError:
            ta_json = None
        if isinstance(ta_json, dict):
            self._log_decision(
                outcome={
                    "decision": ta_json.get("decision", "unknown"),
                    "justification": ta_json.get("justification", ""),
                },
                agent_id="did:university:rubric-ta-martins",
                alternatives=ta_json.get("alternatives_considered"),
            )
        return result.raw

    @listen(ta_review)
    def grade_commit(self, ta_output):
        """Step 3: Grade commit activity — must follow the TA review window."""
        prov: PROVGraph = self.state["_prov"]
        t_commit = datetime.now(timezone.utc).isoformat()
        prov.add_activity(
            "act-grade-commit",
            "Grade committed after TA review",
            started_at=t_commit,
            ended_at=t_commit,
            method="grade_commit",
        )
        prov.add_entity(
            "art-final-grade",
            "Final committed grade",
            artifact_type="semantic_extraction",
        )
        prov.was_generated_by("art-final-grade", "act-grade-commit")
        prov.was_associated_with("act-grade-commit", "did:university:rubric-ta-martins")
        prov.used("act-grade-commit", "art-oversight")
        prov.was_informed_by("act-grade-commit", "act-oversight")

        prov_turtle = prov.serialize("turtle")
        (_out.current / "education_rubric_ta_review_prov.ttl").write_text(prov_turtle)

        self._cleanup()
        print(f"[Rubric/TA-Review] Outputs saved to {_out.current}/")
        return ta_output

    @staticmethod
    def _default_ta_input() -> dict:
        return {
            "submission_summary": (
                "Student S-98765 summative assessment. AI aggregate score B+ (87/100) "
                "across 4 rubric criteria. 8 feedback sentences generated. TA review "
                "required before grade commit."
            ),
            "ai_output": "Pre-committed by AI grading system.",
            "rubric_version": RUBRIC_ID,
        }


# =============================================================================
# Combined audit — three scenarios
# =============================================================================

class RubricAuditFlow(Flow):
    """Combined Rubric audit — three scenarios, three verifiers, one report.

    Scenario A: ``verify_negative_proof`` + ``verify_workflow_isolation``.
    Scenario B: ``verify_rubric_grounding``.
    Scenario C: ``verify_temporal_oversight``.
    """

    @start()
    def init(self):
        return self.state.get("audit_input", {})

    @listen(init)
    def run_audit(self, audit_input):
        print("[Rubric/Audit] Running three-scenario verification...")

        grading_prov_path = _out.current / "education_rubric_prov.ttl"
        equity_prov_path = _out.current / "education_rubric_equity_prov.ttl"
        ta_review_prov_path = _out.current / "education_rubric_ta_review_prov.ttl"
        sentences_path = _out.current / "education_rubric_feedback_sentences.json"

        for p in (grading_prov_path, equity_prov_path, ta_review_prov_path, sentences_path):
            if not p.exists():
                print(f"[Rubric/Audit] ERROR: Missing input {p.name}. Run the upstream Rubric flows first.")
                return {"error": f"Missing input: {p.name}"}

        # Load PROV graphs
        grading_prov = PROVGraph(context_id="rubric-grading")
        grading_prov._graph.parse(data=grading_prov_path.read_text(), format="turtle")

        equity_prov = PROVGraph(context_id="rubric-equity")
        equity_prov._graph.parse(data=equity_prov_path.read_text(), format="turtle")

        ta_prov = PROVGraph(context_id="rubric-ta-review")
        ta_prov._graph.parse(data=ta_review_prov_path.read_text(), format="turtle")

        sentences_meta = json.loads(sentences_path.read_text())
        feedback_sentence_ids = sentences_meta.get("feedback_sentence_ids", [])
        submission_entity_id = sentences_meta.get("submission_entity_id", "art-ingestion")

        # ── Scenario A: negative proof + workflow isolation ──
        # The grading pipeline produces its final artifact as "art-feedback"
        # (the aggregate feedback step). Identity/demographic artifacts should
        # not appear in that chain.
        negative_proof = verify_negative_proof(
            prov=grading_prov,
            decision_entity_id="art-feedback",
            excluded_artifact_types=[
                "biometric", "sensitive", "identity_data", "demographic",
            ],
        )
        workflow_isolation = verify_workflow_isolation(grading_prov, equity_prov)

        # ── Scenario B: rubric grounding ──
        rubric_grounding = verify_rubric_grounding(
            prov=grading_prov,
            feedback_sentence_ids=feedback_sentence_ids,
            submission_entity_id=submission_entity_id,
        )

        # ── Scenario C: temporal oversight ──
        temporal_oversight = verify_temporal_oversight(
            prov=ta_prov,
            ai_activity_id="act-ai-feedback",
            human_activities=["act-oversight"],
            min_review_seconds=5.0,  # simulated (production: 300.0)
        )

        # ── Narrative audit via LLM crew ──
        t0 = datetime.now(timezone.utc)
        crew_result = RubricAuditCrew().crew().kickoff(inputs={
            "negative_proof_passed": str(negative_proof.passed),
            "negative_proof_evidence": json.dumps(negative_proof.evidence),
            "workflow_isolation_passed": str(workflow_isolation.passed),
            "workflow_isolation_evidence": json.dumps(workflow_isolation.evidence),
            "rubric_grounding_passed": str(rubric_grounding.passed),
            "rubric_grounding_evidence": json.dumps(rubric_grounding.evidence),
            "temporal_oversight_passed": str(temporal_oversight.passed),
            "temporal_oversight_evidence": json.dumps(temporal_oversight.evidence),
        })
        t1 = datetime.now(timezone.utc)

        report = {
            "scenario_a": {
                "negative_proof": {
                    "passed": negative_proof.passed,
                    "evidence": negative_proof.evidence,
                    "message": negative_proof.message,
                },
                "workflow_isolation": {
                    "passed": workflow_isolation.passed,
                    "evidence": workflow_isolation.evidence,
                    "message": workflow_isolation.message,
                },
            },
            "scenario_b": {
                "rubric_grounding": {
                    "passed": rubric_grounding.passed,
                    "evidence": rubric_grounding.evidence,
                    "message": rubric_grounding.message,
                },
            },
            "scenario_c": {
                "temporal_oversight": {
                    "passed": temporal_oversight.passed,
                    "evidence": temporal_oversight.evidence,
                    "message": temporal_oversight.message,
                },
            },
            "audit_narrative": crew_result.raw,
            "verified_at": t1.isoformat(),
            "overall_passed": all(
                r.passed for r in (
                    negative_proof, workflow_isolation,
                    rubric_grounding, temporal_oversight,
                )
            ),
        }

        (_out.current / "education_rubric_audit.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False)
        )
        print(f"[Rubric/Audit] Overall: {'PASSED' if report['overall_passed'] else 'FAILED'}")
        print(f"[Rubric/Audit]   Scenario A negative_proof:       "
              f"{'PASS' if negative_proof.passed else 'FAIL'}")
        print(f"[Rubric/Audit]   Scenario A workflow_isolation:   "
              f"{'PASS' if workflow_isolation.passed else 'FAIL'}")
        print(f"[Rubric/Audit]   Scenario B rubric_grounding:     "
              f"{'PASS' if rubric_grounding.passed else 'FAIL'} "
              f"({rubric_grounding.evidence.get('grounded_count', 0)}/"
              f"{rubric_grounding.evidence.get('feedback_sentences_checked', 0)} grounded)")
        print(f"[Rubric/Audit]   Scenario C temporal_oversight:   "
              f"{'PASS' if temporal_oversight.passed else 'FAIL'} "
              f"({temporal_oversight.evidence.get('total_review_seconds', 0):.0f}s review)")
        print(f"[Rubric/Audit] Report saved to {_out.current}/education_rubric_audit.json")
        return report

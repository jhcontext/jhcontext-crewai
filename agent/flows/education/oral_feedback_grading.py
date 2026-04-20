"""Rubric-Grounded *Oral* Grading Flows — three scenarios on a 6-agent pipeline.

Multimodal extension of ``agent/flows/education/rubric_feedback_grading.py``.
The input is a student audio submission; the feedback agent binds each
sentence to a millisecond window on the source recording; the audit runs
``verify_multimodal_binding`` instead of ``verify_rubric_grounding``.

Flows:
  * ``OralGradingFlow``   — 3-agent pipeline
                            (audio ingestion → criterion-scoring →
                             feedback with per-sentence envelopes)
  * ``OralEquityFlow``    — isolated equity workflow (Scenario A)
  * ``OralTAReviewFlow``  — TA review with fine-grained document-access
                            PROV events, including an audio-open event
                            (Scenario C temporal oversight)
  * ``OralAuditFlow``     — runs three SDK verifiers (negative-proof,
                            multimodal-binding, temporal-oversight) plus
                            workflow-isolation, and a narrative audit
                            crew

Output filenames (written to ``_out.current/``):
  education_oral_grading_envelope.json    flow-level envelope
  education_oral_envelopes.json           per-task + per-feedback-sentence
  education_oral_prov.ttl                 grading pipeline PROV
  education_oral_metrics.json             timing metrics
  education_oral_equity_prov.ttl          isolated equity PROV
  education_oral_ta_review_prov.ttl       TA review PROV (w/ audio-open)
  education_oral_audit.json               three-scenario audit report
"""

from __future__ import annotations

import hashlib
import json
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.education.oral_feedback_grading.crew import (
    OralAudioIngestionCrew,
    OralAuditCrew,
    OralCriterionScoringCrew,
    OralEquityCrew,
    OralFeedbackCrew,
    OralTAReviewCrew,
)
from agent.protocol.context_mixin import ContextMixin

from jhcontext import ArtifactType, PROVGraph, RiskLevel
from jhcontext.audit import (
    generate_audit_report,
    verify_integrity,
    verify_multimodal_binding,
    verify_negative_proof,
    verify_temporal_oversight,
    verify_workflow_isolation,
)

import agent.output_dir as _out


RUBRIC_ID = "oral_rubric_v1.0"
STT_MODEL_ID = "whisper-large-v3"
FEEDBACK_MODEL_ID = "claude-sonnet-4-6"
PROMPT_TEMPLATE_ID = "oral_fb_per_criterion_v1"
PROMPT_TEMPLATE_HASH = (
    "sha256:" + hashlib.sha256(PROMPT_TEMPLATE_ID.encode()).hexdigest()[:16] + "..."
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json_array(text: str) -> list[dict]:
    """Best-effort extraction of a JSON array from an LLM-generated string.

    Mirrors the helper in ``rubric_feedback_grading.py``.
    """
    text = text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"(\[[\s\S]*\])", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return []


def _evidence_window_hash(audio_hash: str, start_ms: int, end_ms: int) -> str:
    """Hash of the audio-window slice identified by (audio_hash, start_ms, end_ms).

    For a real deployment this would hash the decoded PCM samples in the
    window. For the offline simulation harness the tuple hash is
    cryptographically equivalent: an auditor recomputes it from the
    content-hashed audio plus the cited window bounds.
    """
    payload = f"{audio_hash}:{start_ms}:{end_ms}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()[:16] + "..."


# =============================================================================
# Scenario A + B (multimodal) shared pipeline — oral grading flow
# =============================================================================

class OralGradingFlow(Flow, ContextMixin):
    """Oral 3-agent pipeline: audio ingestion → criterion-scoring → feedback.

    Emits one PAC-AI envelope for the flow, one per-task envelope for each of
    the three stages, and **one additional envelope per LLM-generated
    feedback sentence** during the feedback stage. Per-sentence envelopes
    carry ``rubricCriterionId`` + ``evidenceSpanHash`` + ``evidenceStartMs`` +
    ``evidenceEndMs`` + ``artifactModality="audio"`` attributes that
    ``verify_multimodal_binding`` will later audit.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_oral_assessment",
            producer="did:university:oral-grading-system",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
        )

        self._register_crew(
            crew_id="crew:oral-grading",
            label="Oral Grading Crew",
            agent_ids=[
                "did:university:oral-audio-ingestion-agent",
                "did:university:oral-criterion-scoring-agent",
                "did:university:oral-feedback-agent",
            ],
        )

        print(f"[Oral/Grading] Initialized context: {context_id}")
        return self.state.get("submission_input", self._default_submission())

    @listen(init)
    def audio_ingestion(self, input_data):
        print("[Oral/Grading] Step 1/3: Audio ingestion + STT alignment...")
        t0 = datetime.now(timezone.utc)
        result = OralAudioIngestionCrew().crew().kickoff(inputs=input_data)
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="audio_ingestion",
            agent_id="did:university:oral-audio-ingestion-agent",
            output=result.raw,
            artifact_type=ArtifactType.AUDIO,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
        )

        self.state["_ingestion_output"] = result.raw
        # Carry the raw audio hash + transcript forward so downstream stages
        # can cite audio windows by (start_ms, end_ms).
        self.state["_audio_hash"] = input_data.get(
            "audio_content_hash",
            "sha256:" + hashlib.sha256(
                input_data.get("audio_uri", "unknown").encode()
            ).hexdigest()[:16] + "...",
        )
        self.state["_transcript"] = input_data.get("transcript", result.raw)
        self.state["_word_timings"] = input_data.get("word_timings", [])
        return result.raw

    @listen(audio_ingestion)
    def criterion_scoring(self, ingestion_output):
        print("[Oral/Grading] Step 2/3: Per-criterion scoring (audio-window evidence)...")
        t0 = datetime.now(timezone.utc)
        result = OralCriterionScoringCrew().crew().kickoff(
            inputs={
                "transcript": self.state.get("_transcript", ""),
                "word_timings": json.dumps(self.state.get("_word_timings", [])),
            }
        )
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="oral_scoring",
            agent_id="did:university:oral-criterion-scoring-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-audio_ingestion"],
        )

        self._log_decision(
            outcome={"aggregate_score": result.raw[:100]},
            agent_id="did:university:oral-criterion-scoring-agent",
        )
        self.state["_scoring_output"] = result.raw
        return result.raw

    @listen(criterion_scoring)
    def feedback_generation(self, scoring_output):
        """Generate 5-8 feedback sentences and emit one envelope per sentence.

        Scenario B (multimodal) load-bearing step: each sentence is bound
        to a rubric criterion, an audio window (start_ms, end_ms), a
        model version, a prompt-template hash, and modality="audio" via
        attributes on the PROV entity.
        """
        print("[Oral/Grading] Step 3/3: Rubric-grounded oral feedback generation...")
        t0 = datetime.now(timezone.utc)
        result = OralFeedbackCrew().crew().kickoff(
            inputs={
                "scoring_output": scoring_output,
                "transcript": self.state.get("_transcript", ""),
                "word_timings": json.dumps(self.state.get("_word_timings", [])),
                "rubric_id": RUBRIC_ID,
                "model_id": FEEDBACK_MODEL_ID,
                "prompt_template_hash": PROMPT_TEMPLATE_HASH,
            }
        )
        t1 = datetime.now(timezone.utc)

        sentences = _extract_json_array(result.raw)
        self.state["_feedback_sentences"] = sentences

        # Record the feedback-generation handoff as ONE aggregate step.
        # Single PAC-AI envelope for the whole oral feedback block (per the
        # protocol: one envelope per handoff). Per-sentence bindings live
        # in the envelope's UserML interpretation layer; per-sentence PROV
        # entities below preserve audit granularity.
        self._persist_step(
            step_name="oral_feedback",
            agent_id="did:university:oral-feedback-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
            used_artifacts=["art-oral_scoring", "art-audio_ingestion"],
        )

        prov: PROVGraph = self.state["_prov"]
        audio_hash = self.state.get("_audio_hash", "sha256:unknown...")
        feedback_activity_id = "act-oral_feedback"  # activity from _persist_step above

        feedback_sentence_ids: list[str] = []
        for i, fs in enumerate(sentences, start=1):
            fs_id = fs.get("sentence_id") or f"oral-fb-{i:02d}"
            art_id = f"art-oral-feedback-{fs_id}"
            span = fs.get("evidence_span") or {}
            start_ms = span.get("start_ms")
            end_ms = span.get("end_ms")
            modality = fs.get("artifact_modality", "audio")

            ev_hash = ""
            if isinstance(start_ms, int) and isinstance(end_ms, int) and end_ms > start_ms:
                ev_hash = _evidence_window_hash(audio_hash, start_ms, end_ms)

            criterion_id = fs.get("rubric_criterion_id") or f"{RUBRIC_ID}#unknown"
            fs_text_hash = "sha256:" + hashlib.sha256(
                json.dumps(fs, ensure_ascii=False).encode()
            ).hexdigest()[:16] + "..."

            prov.add_entity(
                art_id,
                f"Oral feedback sentence {fs_id} assessing {criterion_id}",
                artifact_type="semantic_extraction",
                content_hash=fs_text_hash,
            )
            prov.was_generated_by(art_id, feedback_activity_id)
            prov.was_derived_from(art_id, "art-audio_ingestion")

            # Modality-aware attributes audited by verify_multimodal_binding
            prov.set_entity_attribute(art_id, "rubricCriterionId", criterion_id)
            prov.set_entity_attribute(art_id, "modelVersion", fs.get("model_version", FEEDBACK_MODEL_ID))
            prov.set_entity_attribute(
                art_id, "promptTemplateHash",
                fs.get("prompt_template_hash", PROMPT_TEMPLATE_HASH),
            )
            prov.set_entity_attribute(art_id, "artifactModality", modality)
            if ev_hash:
                prov.set_entity_attribute(art_id, "evidenceSpanHash", ev_hash)
                if isinstance(start_ms, int):
                    prov.set_entity_attribute(art_id, "evidenceStartMs", start_ms)
                if isinstance(end_ms, int):
                    prov.set_entity_attribute(art_id, "evidenceEndMs", end_ms)
            feedback_sentence_ids.append(art_id)

        self.state["_feedback_sentence_ids"] = feedback_sentence_ids
        return result.raw

    @listen(feedback_generation)
    def grading_complete(self, feedback_output):
        task_envelopes = self.state.get("_task_envelopes", [])
        (_out.current / "education_oral_envelopes.json").write_text(
            json.dumps(task_envelopes, indent=2)
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "education_oral_prov.ttl").write_text(prov_turtle)

        (_out.current / "education_oral_feedback_sentences.json").write_text(
            json.dumps({
                "feedback_sentence_ids": self.state.get("_feedback_sentence_ids", []),
                "feedback_sentences": self.state.get("_feedback_sentences", []),
                "context_id": self.state["_context_id"],
                "submission_entity_id": "art-audio_ingestion",
                "modality": "audio",
            }, indent=2, ensure_ascii=False)
        )

        metrics = self._finalize_metrics()
        (_out.current / "education_oral_metrics.json").write_text(json.dumps(metrics, indent=2))

        self._cleanup()
        print(f"[Oral/Grading] {len(self.state.get('_feedback_sentence_ids', []))} "
              f"per-sentence envelopes emitted; outputs in {_out.current}/")
        return feedback_output

    @staticmethod
    def _default_submission() -> dict:
        # A short fixed fixture so the flow runs offline; production calls
        # would pass a real audio_uri + content hash + aligned transcript.
        word_timings = [
            {"word": "Today",   "start_ms":  450, "end_ms":  900},
            {"word": "I",       "start_ms":  950, "end_ms": 1050},
            {"word": "argue",   "start_ms": 1100, "end_ms": 1500},
            {"word": "carbon",  "start_ms": 2450, "end_ms": 2850},
            {"word": "pricing", "start_ms": 2900, "end_ms": 3400},
            {"word": "is",      "start_ms": 3450, "end_ms": 3600},
            {"word": "effective", "start_ms": 5050, "end_ms": 5600},
        ]
        transcript = " ".join(w["word"] for w in word_timings)
        audio_uri = "urn:university:oral:S-ORAL-98765.wav"
        audio_content_hash = (
            "sha256:" + hashlib.sha256(audio_uri.encode()).hexdigest()[:16] + "..."
        )
        return {
            "student_id": "S-ORAL-98765",
            "presentation_topic": "The Role of Carbon Pricing in Climate Policy",
            "duration_ms": 19000,
            "audio_uri": audio_uri,
            "audio_content_hash": audio_content_hash,
            "transcript": transcript,
            "word_timings": word_timings,
        }


# =============================================================================
# Scenario A — isolated equity workflow (oral)
# =============================================================================

class OralEquityFlow(Flow, ContextMixin):
    """Oral equity reporting workflow — isolated from the oral grading pipeline.

    Clone of the ``RubricEquityFlow`` with oral-specific output filenames.
    Produces ``education_oral_equity_prov.ttl`` that the audit flow uses
    for ``verify_workflow_isolation``.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_oral_equity_reporting",
            producer="did:university:equity-system-oral",
            risk_level=RiskLevel.MEDIUM,
            human_oversight=False,
        )

        self._register_crew(
            crew_id="crew:oral-equity",
            label="Oral Equity Crew",
            agent_ids=["did:university:oral-equity-agent"],
        )

        print(f"[Oral/Equity] Initialized context: {context_id}")
        return self.state.get("identity_input", self._default_identity())

    @listen(init)
    def equity_reporting(self, identity_data):
        print("[Oral/Equity] Generating equity report (isolated workflow)...")
        t0 = datetime.now(timezone.utc)
        result = OralEquityCrew().crew().kickoff(inputs=identity_data)
        t1 = datetime.now(timezone.utc)

        self._persist_step(
            step_name="equity",
            agent_id="did:university:oral-equity-agent",
            output=result.raw,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            started_at=t0.isoformat(),
            ended_at=t1.isoformat(),
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "education_oral_equity_prov.ttl").write_text(prov_turtle)

        self._cleanup()
        print(f"[Oral/Equity] Outputs saved to {_out.current}/")
        return result.raw

    @staticmethod
    def _default_identity() -> dict:
        return {
            "aggregate_demographics": (
                "Cohort of 80 oral-assessment candidates: 55% female, 45% male; "
                "40% first-generation; 22% English as additional language."
            ),
        }


# =============================================================================
# Scenario C — TA review with temporal oversight (oral variant)
# =============================================================================

# Simulated document-access durations (seconds). Production TA sessions
# would use real interaction timings captured by the oral-grading platform,
# including the audio-player's play/pause events over each cited window.
SOURCE_DOCUMENTS = [
    ("act-ta-open-audio",       "TA opens student audio submission",   "art-ta-audio",       "Audio submission",        5),
    ("act-ta-open-transcript",  "TA opens transcript + word-timings",  "art-ta-transcript",  "Transcript + alignment",  3),
    ("act-ta-open-rubric",      "TA opens rubric",                     "art-ta-rubric",      "Rubric (oral_rubric_v1.0)", 2),
    ("act-ta-open-ai-score",    "TA opens AI aggregate score",         "art-ta-ai-score",    "AI aggregate score",      2),
    ("act-ta-open-ai-feedback", "TA opens AI feedback block",          "art-ta-ai-feedback", "AI feedback block",       4),
]


class OralTAReviewFlow(Flow, ContextMixin):
    """Oral Scenario C — TA review with temporal oversight, including audio-open.

    Direct port of ``RubricTAReviewFlow`` with an extra fine-grained
    document-access activity for the audio artifact itself — the TA must
    actually listen to the submission, not just read the transcript.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="education_oral_ta_review",
            producer="did:university:ta-review-system-oral",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
        )

        self._register_crew(
            crew_id="crew:oral-ta-review",
            label="Oral TA Review Crew",
            agent_ids=[
                "did:university:oral-ai-feedback-agent",
                "did:university:oral-ta-martins",
            ],
        )

        print(f"[Oral/TA-Review] Initialized context: {context_id}")
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
            "AI oral-feedback generation (reference activity for temporal comparison)",
            started_at=t_ai.isoformat(),
            ended_at=t_ai.isoformat(),
        )
        prov.add_agent(
            "did:university:oral-ai-feedback-agent",
            "AI Oral Feedback Agent",
            role="evaluator",
        )
        prov.was_associated_with("act-ai-feedback", "did:university:oral-ai-feedback-agent")
        self.state["_ai_activity_ts"] = t_ai.isoformat()
        return ta_input

    @listen(record_ai_output)
    def ta_review(self, ta_input):
        """Step 2: TA review with fine-grained PROV events (per doc access)."""
        print("[Oral/TA-Review] TA review with document-access events (incl. audio)...")

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

        result = OralTAReviewCrew().crew().kickoff(inputs=ta_input)
        overall_t1 = datetime.now(timezone.utc)

        self._persist_oversight_events(
            events=oversight_events,
            oversight_agent_id="did:university:oral-ta-martins",
            summary_output=result.raw,
            overall_started_at=overall_t0.isoformat(),
            overall_ended_at=overall_t1.isoformat(),
        )

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
                agent_id="did:university:oral-ta-martins",
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
            "Oral grade committed after TA review",
            started_at=t_commit,
            ended_at=t_commit,
            method="grade_commit",
        )
        prov.add_entity(
            "art-final-grade",
            "Final committed oral grade",
            artifact_type="semantic_extraction",
        )
        prov.was_generated_by("art-final-grade", "act-grade-commit")
        prov.was_associated_with("act-grade-commit", "did:university:oral-ta-martins")
        prov.used("act-grade-commit", "art-oversight")
        prov.was_informed_by("act-grade-commit", "act-oversight")

        prov_turtle = prov.serialize("turtle")
        (_out.current / "education_oral_ta_review_prov.ttl").write_text(prov_turtle)

        self._cleanup()
        print(f"[Oral/TA-Review] Outputs saved to {_out.current}/")
        return ta_output

    @staticmethod
    def _default_ta_input() -> dict:
        return {
            "submission_summary": (
                "Student S-ORAL-98765 summative oral assessment (19s recording). "
                "AI aggregate score B+ (85/100) across 4 rubric criteria. "
                "6 feedback sentences generated, each bound to an audio window. "
                "TA review required (including listening to each cited window) "
                "before grade commit."
            ),
            "ai_output": "Pre-committed by AI oral-grading system.",
            "rubric_version": RUBRIC_ID,
        }


# =============================================================================
# Combined audit — three oral scenarios
# =============================================================================

class OralAuditFlow(Flow):
    """Combined Oral audit — three scenarios, three verifiers, one report.

    Scenario A:          verify_negative_proof + verify_workflow_isolation.
    Scenario B (mmodal): verify_multimodal_binding.
    Scenario C:          verify_temporal_oversight.
    """

    @start()
    def init(self):
        return self.state.get("audit_input", {})

    @listen(init)
    def run_audit(self, audit_input):
        print("[Oral/Audit] Running three-scenario verification...")

        grading_prov_path = _out.current / "education_oral_prov.ttl"
        equity_prov_path = _out.current / "education_oral_equity_prov.ttl"
        ta_review_prov_path = _out.current / "education_oral_ta_review_prov.ttl"
        sentences_path = _out.current / "education_oral_feedback_sentences.json"

        for p in (grading_prov_path, equity_prov_path, ta_review_prov_path, sentences_path):
            if not p.exists():
                print(f"[Oral/Audit] ERROR: Missing input {p.name}. Run the upstream Oral flows first.")
                return {"error": f"Missing input: {p.name}"}

        grading_prov = PROVGraph(context_id="oral-grading")
        grading_prov._graph.parse(data=grading_prov_path.read_text(), format="turtle")

        equity_prov = PROVGraph(context_id="oral-equity")
        equity_prov._graph.parse(data=equity_prov_path.read_text(), format="turtle")

        ta_prov = PROVGraph(context_id="oral-ta-review")
        ta_prov._graph.parse(data=ta_review_prov_path.read_text(), format="turtle")

        sentences_meta = json.loads(sentences_path.read_text())
        feedback_sentence_ids = sentences_meta.get("feedback_sentence_ids", [])
        submission_entity_id = sentences_meta.get("submission_entity_id", "art-audio_ingestion")
        modality = sentences_meta.get("modality", "audio")

        # ── Scenario A: negative proof + workflow isolation ──
        negative_proof = verify_negative_proof(
            prov=grading_prov,
            decision_entity_id="art-oral_feedback",
            excluded_artifact_types=[
                "biometric", "sensitive", "identity_data", "demographic",
            ],
        )
        workflow_isolation = verify_workflow_isolation(grading_prov, equity_prov)

        # ── Scenario B (multimodal): rubric + audio-window binding ──
        multimodal_binding = verify_multimodal_binding(
            prov=grading_prov,
            feedback_sentence_ids=feedback_sentence_ids,
            submission_entity_id=submission_entity_id,
            modality=modality,
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
        crew_result = OralAuditCrew().crew().kickoff(inputs={
            "negative_proof_passed": str(negative_proof.passed),
            "negative_proof_evidence": json.dumps(negative_proof.evidence),
            "workflow_isolation_passed": str(workflow_isolation.passed),
            "workflow_isolation_evidence": json.dumps(workflow_isolation.evidence),
            "multimodal_binding_passed": str(multimodal_binding.passed),
            "multimodal_binding_evidence": json.dumps(multimodal_binding.evidence),
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
            "scenario_b_multimodal": {
                "multimodal_binding": {
                    "passed": multimodal_binding.passed,
                    "evidence": multimodal_binding.evidence,
                    "message": multimodal_binding.message,
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
                    multimodal_binding, temporal_oversight,
                )
            ),
        }

        (_out.current / "education_oral_audit.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False)
        )
        print(f"[Oral/Audit] Overall: {'PASSED' if report['overall_passed'] else 'FAILED'}")
        print(f"[Oral/Audit]   Scenario A negative_proof:        "
              f"{'PASS' if negative_proof.passed else 'FAIL'}")
        print(f"[Oral/Audit]   Scenario A workflow_isolation:    "
              f"{'PASS' if workflow_isolation.passed else 'FAIL'}")
        print(f"[Oral/Audit]   Scenario B multimodal_binding:    "
              f"{'PASS' if multimodal_binding.passed else 'FAIL'} "
              f"({multimodal_binding.evidence.get('grounded_count', 0)}/"
              f"{multimodal_binding.evidence.get('feedback_sentences_checked', 0)} grounded; "
              f"modalities={multimodal_binding.evidence.get('modality_counts', {})})")
        print(f"[Oral/Audit]   Scenario C temporal_oversight:    "
              f"{'PASS' if temporal_oversight.passed else 'FAIL'} "
              f"({temporal_oversight.evidence.get('total_review_seconds', 0):.0f}s review)")
        print(f"[Oral/Audit] Report saved to {_out.current}/education_oral_audit.json")
        return report

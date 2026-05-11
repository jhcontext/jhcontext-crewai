"""Hiring multi-agent flow.

Wires the six-task ``HiringCrew`` to the PAC-AI protocol:

  1. Each task outputs a ``FlatEnvelope`` (``output_pydantic=FlatEnvelope``).
  2. ``hiring_task_callback`` rehydrates each FlatEnvelope to a full
     ``Envelope`` via ``flat.to_envelope()``, signs + content-hashes it via
     ``EnvelopeBuilder``, records the activity in a single ``PROVGraph``,
     and applies ``ForwardingEnforcer`` so the next task sees only the
     prior task's ``semantic_payload`` -- never raw artifacts.
  3. After the crew finishes, the flow records the recruiter (a human
     PROV agent) reviewing the decision-support packet, runs three
     verifier checkpoints (procurement / in-flight / cohort-ready), and
     writes everything to ``output/hiring/``.

The flow uses ONLY public ``jhcontext>=0.5,<0.6`` PyPI exports:
``EnvelopeBuilder``, ``PROVGraph``, ``ForwardingEnforcer``,
``ForwardingPolicy``, ``RiskLevel``, ``ArtifactType``,
``observation``/``interpretation``, plus ``FlatEnvelope`` from the
``jhcontext.flat_envelope`` module.

Set ``HIRING_USE_MOCK_LLM=1`` (or pass ``llm=MockHiringLLM()``) to run
without API keys; results are deterministic.
"""

from __future__ import annotations

import json
import os
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jhcontext import (
    AbstractionLevel,
    ArtifactType,
    EnvelopeBuilder,
    ForwardingEnforcer,
    ForwardingPolicy,
    PROVGraph,
    RiskLevel,
    TemporalScope,
    verify_integrity,
    verify_negative_proof,
    verify_temporal_oversight,
)
from jhcontext.flat_envelope import FlatEnvelope
from jhcontext.models import Envelope

from agent.crews.hiring._verifiers import (
    feature_usage_census,
    fixtures as fx,
    four_fifths_ratio,
    verify_ai_literacy_attestation,
    verify_candidate_notice,
    verify_incident_attestation,
    verify_input_data_attestation,
    verify_no_prohibited_practice,
    verify_sourcing_neutrality,
    verify_workforce_notice,
)


OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output" / "hiring"
ENVELOPE_DIR = OUTPUT_ROOT / "envelopes"
DIFF_DIR = OUTPUT_ROOT / "forwarding_diff"
PROV_DIR = OUTPUT_ROOT / "prov"
AUDIT_DIR = OUTPUT_ROOT / "audit"

HIRING_CREW_ID = "crew:hiring"
HIRING_AGENT_DIDS = (
    "did:vendor:sourcing-agent",
    "did:vendor:parsing-agent",
    "did:vendor:screening-agent",
    "did:vendor:interview-agent",
    "did:vendor:ranking-agent",
    "did:vendor:decision-support-agent",
)


# ---------------------------------------------------------------------------
# State container threaded through the task_callback
# ---------------------------------------------------------------------------

@dataclass
class HiringFlowState:
    """Multi-stage hiring pipeline state.

    Carries one ForwardingEnforcer per policy because SDK v0.6 fixes each
    enforcer to a single policy and disallows mixing. The hiring pipeline
    is intentionally two composed pipelines: a one-step raw sourcing stage,
    then a five-step semantic decision stage (parsing → decision_support).
    The terminal artifact of stage 1 feeds stage 2 — see ``enforcer_for()``.
    """
    context_id: str
    prov: PROVGraph
    raw_enforcer: ForwardingEnforcer
    sem_enforcer: ForwardingEnforcer
    envelopes_by_step: dict[str, Envelope] = field(default_factory=dict)
    raw_outputs_by_step: dict[str, str] = field(default_factory=dict)
    forwarded_outputs_by_step: dict[str, str] = field(default_factory=dict)
    step_order: list[str] = field(default_factory=list)
    decision_timestamp: str = ""

    def previous_step(self) -> str | None:
        return self.step_order[-1] if self.step_order else None

    def enforcer_for(self, envelope: Envelope) -> ForwardingEnforcer:
        """Pick the enforcer whose policy matches the envelope's declaration."""
        declared = envelope.compliance.forwarding_policy
        if declared == ForwardingPolicy.RAW_FORWARD:
            return self.raw_enforcer
        return self.sem_enforcer


# ---------------------------------------------------------------------------
# task_callback wiring SDK forwarding + persistence around every CrewAI task
# ---------------------------------------------------------------------------

def make_task_callback(state: HiringFlowState):
    """Return a CrewAI task_callback bound to the given flow state.

    For each task, in order:

    1. Read ``output.pydantic`` -> ``FlatEnvelope`` -> ``Envelope`` via SDK.
    2. Sign + content-hash the envelope.
    3. Record ``before`` snapshot for the forwarding-diff renderer.
    4. Apply ``ForwardingEnforcer.resolve()`` to determine effective policy.
    5. Apply ``ForwardingEnforcer.filter_output()`` -> rewrite ``output.raw``.
    6. Record ``after`` snapshot.
    7. Add the envelope's artifact + activity + agent + dependencies to PROV.
    """

    def callback(task_output: Any) -> Any:
        flat = getattr(task_output, "pydantic", None)
        if not isinstance(flat, FlatEnvelope):
            # Tolerate raw JSON fallback (e.g. agent ignored output_pydantic).
            try:
                flat = FlatEnvelope.model_validate_json(
                    getattr(task_output, "raw", "{}"),
                )
            except Exception:
                return task_output

        # 1. Rehydrate full Envelope.
        envelope = flat.to_envelope()
        if not envelope.scope:
            return task_output  # nothing useful to record

        step_name = envelope.scope.replace("hiring_", "") or flat.artifact_id
        agent_did = envelope.producer or f"did:vendor:{step_name}-agent"

        # 2. Sign so verify_integrity passes downstream.
        signed_builder = (
            EnvelopeBuilder()
            .set_producer(envelope.producer)
            .set_scope(envelope.scope)
            .set_risk_level(envelope.compliance.risk_level)
            .set_forwarding_policy(envelope.compliance.forwarding_policy)
            .set_human_oversight(envelope.compliance.human_oversight_required)
            .set_semantic_payload(envelope.semantic_payload)
        )
        for art in envelope.artifacts_registry:
            signed_builder.add_artifact(
                artifact_id=art.artifact_id,
                artifact_type=art.type,
                content_hash=art.content_hash or "sha256:" + ("0" * 64),
                model=art.model,
                **art.metadata,
            )
        for di in envelope.decision_influence:
            signed_builder.add_decision_influence(
                agent=di.agent,
                categories=list(di.categories),
                influence_weights=dict(di.influence_weights),
                confidence=di.confidence,
                abstraction_level=di.abstraction_level,
                temporal_scope=di.temporal_scope,
            )
        signed = signed_builder.sign(agent_did).build()

        state.envelopes_by_step[step_name] = signed
        state.step_order.append(step_name)

        # 3. Forwarding-diff: capture before-shape (full envelope JSON).
        before_blob = json.dumps(
            signed.model_dump(mode="json", exclude_none=True),
            indent=2, default=str, ensure_ascii=False,
        )
        state.raw_outputs_by_step[step_name] = before_blob

        # 4 + 5. Pick the enforcer for this stage (raw for sourcing, semantic
        # for parsing+). Each enforcer is locked to one policy in SDK v0.6,
        # so we route by the envelope's declared policy.
        enforcer = state.enforcer_for(signed)
        effective_policy = enforcer.resolve(signed)
        forwarded = enforcer.filter_output(signed, effective_policy)
        state.forwarded_outputs_by_step[step_name] = forwarded
        task_output.raw = forwarded

        # 7. PROV: artifact entity + activity + agent association + deps.
        primary_art = (
            signed.artifacts_registry[0].artifact_id
            if signed.artifacts_registry else f"art-{step_name}"
        )
        primary_type = (
            signed.artifacts_registry[0].type.value
            if signed.artifacts_registry else "semantic_extraction"
        )
        state.prov.add_entity(
            primary_art,
            f"{step_name} output",
            artifact_type=primary_type,
            content_hash=signed.proof.content_hash,
        )
        activity_id = f"act-{step_name}"
        now_iso = datetime.now(timezone.utc).isoformat()
        state.prov.add_activity(activity_id, step_name,
                                started_at=now_iso, ended_at=now_iso)
        state.prov.add_agent(agent_did, agent_did, role=step_name)
        state.prov.acted_on_behalf_of(agent_did, HIRING_CREW_ID)
        state.prov.was_associated_with(activity_id, agent_did)
        state.prov.was_generated_by(primary_art, activity_id)
        if len(state.step_order) >= 2:
            prev_step = state.step_order[-2]
            prev_env = state.envelopes_by_step[prev_step]
            if prev_env.artifacts_registry:
                prev_art = prev_env.artifacts_registry[0].artifact_id
                state.prov.used(activity_id, prev_art)
                state.prov.was_derived_from(primary_art, prev_art)

        if step_name == "decision_support":
            state.decision_timestamp = now_iso

        return task_output

    return callback


# ---------------------------------------------------------------------------
# Recruiter review (human-in-the-loop, recorded as PROV activity only)
# ---------------------------------------------------------------------------

def _record_recruiter_review(
    state: HiringFlowState,
    *,
    minutes_per_candidate: float = 4.0,
    n_candidates: int = 5,
) -> tuple[datetime, datetime]:
    """Recruiter reviews the decision-support packet (Art. 14 oversight).

    The recruiter is an external human PROV agent (NOT in the crew); we set
    her competence record so verify_ai_literacy_attestation passes.
    """
    competence = fx.recruiter_competence_record()
    state.prov.add_agent("recruiter-jane", "Jane Doe", role="recruiter")
    state.prov.set_entity_attribute(
        "recruiter-jane", "competenceRecordHash",
        competence.competence_record_hash,
    )
    state.prov.set_entity_attribute(
        "recruiter-jane", "competenceRecordSigner",
        competence.competence_record_signer,
    )

    decision_dt = (
        datetime.fromisoformat(state.decision_timestamp)
        if state.decision_timestamp
        else datetime.now(timezone.utc)
    )
    review_start = decision_dt + timedelta(minutes=5)
    review_end = review_start + timedelta(seconds=minutes_per_candidate * 60 * n_candidates)

    state.prov.add_activity(
        "recruiter-review",
        "Recruiter reviews decision_support packet (Art. 14 oversight)",
        started_at=review_start.isoformat(),
        ended_at=review_end.isoformat(),
        method="manual review of semantic_payload only",
    )
    state.prov.was_associated_with("recruiter-review", "recruiter-jane")
    if "decision_support" in state.envelopes_by_step:
        ds_art = state.envelopes_by_step["decision_support"].artifacts_registry[0].artifact_id
        state.prov.used("recruiter-review", ds_art)
    return review_start, review_end


# ---------------------------------------------------------------------------
# Procurement attestations (added before the audit checkpoint)
# ---------------------------------------------------------------------------

def _augment_with_attestations(envelope: Envelope, *, with_violation: bool) -> Envelope:
    """Re-bake envelope to include the four attestations that procurement
    governance requires (workforce notice, candidate notice, AI literacy,
    input data) plus the targeted-targeting-attr signal for sourcing.

    Done outside the LLM so the test harness is deterministic and doesn't
    rely on the LLM emitting attestation artifacts in its FlatEnvelope.
    """
    ts = fx.default_attestation_timestamps()
    models = fx.vendor_models(with_violation=with_violation)
    targeting = fx.sourcing_targeting_params(with_violation=with_violation)

    b = (
        EnvelopeBuilder()
        .set_producer(envelope.producer)
        .set_scope(envelope.scope)
        .set_risk_level(envelope.compliance.risk_level)
        .set_forwarding_policy(envelope.compliance.forwarding_policy)
        .set_human_oversight(envelope.compliance.human_oversight_required)
        .set_semantic_payload(envelope.semantic_payload)
    )
    for art in envelope.artifacts_registry:
        b.add_artifact(
            artifact_id=art.artifact_id,
            artifact_type=art.type,
            content_hash=art.content_hash or "sha256:" + "0" * 64,
            model=art.model,
            **art.metadata,
        )
    # Workforce notice.
    b.add_artifact(
        artifact_id="att-workforce",
        artifact_type=ArtifactType.TOOL_RESULT,
        content_hash="sha256:wf-collective-notice-2026Q1",
        kind="workforce_notice_attestation",
        signer=fx.DEPLOYER_SIGNER,
        attestation_hash="sha256:wf-2026Q1",
        attestation_timestamp=ts.workforce_notice.isoformat(),
    )
    # Per-candidate notice (one for the demo).
    b.add_artifact(
        artifact_id="att-cand-notice",
        artifact_type=ArtifactType.TOOL_RESULT,
        content_hash="sha256:cand-notice-001",
        kind="candidate_notice_attestation",
        candidate_id="cand-0001",
        signer="did:deployer:notification-service",
        attestation_hash="sha256:cand-notice-cand-0001",
        attestation_timestamp=(
            datetime.now(timezone.utc) - timedelta(days=2)
        ).isoformat(),
    )
    # Vendor models with capabilities + governance attestations.
    for m in models:
        b.add_artifact(
            artifact_id=m.artifact_id,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            content_hash=m.content_hash(),
            model=m.model,
            capabilities=list(m.capabilities),
            data_governance_attestation_ref=m.data_governance_attestation_ref,
            data_governance_attestation_signer=m.data_governance_attestation_signer,
        )
    # Decision artifact (timestamped earlier than env.created_at default).
    b.add_artifact(
        artifact_id="art-decision",
        artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
        content_hash="sha256:" + "d" * 64,
        kind="decision",
    )
    return b.sign(fx.COMPLIANCE_SIGNER).build(), targeting


def _attach_targeting_to_prov(prov: PROVGraph, sourcing_entity: str,
                              targeting: list[str]) -> None:
    for p in targeting:
        prov.set_entity_attribute(sourcing_entity, "adTargetingParam", p)


# ---------------------------------------------------------------------------
# Audit checkpoints
# ---------------------------------------------------------------------------

@dataclass
class HiringAuditResult:
    procurement: dict[str, Any] = field(default_factory=dict)
    inflight: dict[str, Any] = field(default_factory=dict)
    overall_passed: bool = False


def _run_procurement_audit(state: HiringFlowState, *,
                           augmented_envelope: Envelope) -> dict:
    sn = verify_sourcing_neutrality(
        state.prov,
        sourcing_decision_entity_id="art-sourcing-decision",
        prohibited_targeting_attrs=list(fx.PROHIBITED_TARGETING_ATTRS),
    )
    npp = verify_no_prohibited_practice(augmented_envelope)
    wn = verify_workforce_notice(augmented_envelope)
    idata = verify_input_data_attestation(augmented_envelope)
    integ = verify_integrity(augmented_envelope)
    results = [sn, npp, wn, idata, integ]
    return {
        "checks": [
            {"check_name": r.check_name, "passed": r.passed, "message": r.message}
            for r in results
        ],
        "overall_passed": all(r.passed for r in results),
    }


def _run_inflight_audit(state: HiringFlowState, *,
                       augmented_envelope: Envelope) -> dict:
    np = verify_negative_proof(
        state.prov,
        decision_entity_id="art-decision_support",
        excluded_artifact_types=["raw_video", "raw_cv_with_identifiers"],
    )
    cn = verify_candidate_notice(augmented_envelope, candidate_id="cand-0001")
    to = verify_temporal_oversight(
        state.prov,
        ai_activity_id="act-decision_support",
        human_activities=["recruiter-review"],
        min_review_seconds=300.0,
    )
    al = verify_ai_literacy_attestation(state.prov,
                                        oversight_activity_id="recruiter-review")
    integ = verify_integrity(augmented_envelope)
    results = [np, cn, to, al, integ]
    return {
        "checks": [
            {"check_name": r.check_name, "passed": r.passed, "message": r.message}
            for r in results
        ],
        "overall_passed": all(r.passed for r in results),
    }


# ---------------------------------------------------------------------------
# Public entry point: run the crew once and audit
# ---------------------------------------------------------------------------

def run_hiring_pipeline(
    *,
    posting_id: str = "POST-2026-Q2-SWE-04",
    inject_violation: bool = False,
    use_mock_llm: bool | None = None,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    """Kick off the six-task hiring crew and run procurement + in-flight audits.

    Returns a metrics dict. Writes signed envelopes, the PROV graph, the
    forwarding-diff snapshots, and audit reports to ``output/hiring/``.
    """
    if use_mock_llm is None:
        use_mock_llm = (
            os.environ.get("HIRING_USE_MOCK_LLM", "").lower() in {"1", "true", "yes"}
            or not os.environ.get("ANTHROPIC_API_KEY")
        )

    envelope_dir = output_root / "envelopes"
    diff_dir = output_root / "forwarding_diff"
    prov_dir = output_root / "prov"
    audit_dir = output_root / "audit"
    for d in (output_root, envelope_dir, diff_dir, prov_dir, audit_dir):
        d.mkdir(parents=True, exist_ok=True)

    metrics: dict = {
        "use_mock_llm": use_mock_llm,
        "inject_violation": inject_violation,
    }
    t_total = _time.perf_counter()

    # PROV graph + ForwardingEnforcer shared across all tasks.
    context_id = f"ctx-hiring-{posting_id.lower()}"
    prov = PROVGraph(context_id)
    prov.add_crew(HIRING_CREW_ID, "Hiring Pipeline Crew")
    for did in HIRING_AGENT_DIDS:
        prov.add_agent(did, did)
        prov.acted_on_behalf_of(did, HIRING_CREW_ID)

    # Hiring is two composed pipelines under SDK v0.6's uniform-policy contract:
    #   stage 1 (sourcing, 1 task)     — raw_forward
    #   stage 2 (parsing → decision, 5) — semantic_forward
    # Stage 1's signed envelope is the input artifact for stage 2.
    raw_enforcer = ForwardingEnforcer(policy=ForwardingPolicy.RAW_FORWARD)
    sem_enforcer = ForwardingEnforcer(policy=ForwardingPolicy.SEMANTIC_FORWARD)
    state = HiringFlowState(
        context_id=context_id,
        prov=prov,
        raw_enforcer=raw_enforcer,
        sem_enforcer=sem_enforcer,
    )

    # Build the crew with the chosen LLM.
    from agent.crews.hiring.hiring_crew import HiringCrew, install_llms
    if use_mock_llm:
        from agent.crews.hiring.llm_mock import MockHiringLLM
        install_llms(classifier=MockHiringLLM())
    else:
        install_llms()  # restore defaults from agent.libs.llms

    hiring = HiringCrew()
    crew_instance = hiring.crew()
    crew_instance.task_callback = make_task_callback(state)

    t_crew = _time.perf_counter()
    crew_instance.kickoff(inputs={
        "posting_id": posting_id,
        "prohibited_targeting_attrs": ", ".join(fx.PROHIBITED_TARGETING_ATTRS),
        "suppressed_identifiers": ", ".join(fx.SUPPRESSED_IDENTIFIERS),
        "_forwarding_preamble": ForwardingPolicy.SEMANTIC_FORWARD.format_preamble("high"),
    })
    metrics["crew_kickoff_ms"] = (_time.perf_counter() - t_crew) * 1000

    # ----- Recruiter review (human-in-the-loop) -----
    review_start, review_end = _record_recruiter_review(
        state, minutes_per_candidate=(0.025 if inject_violation else 4.0),
        n_candidates=5,
    )
    metrics["recruiter_review_seconds"] = (review_end - review_start).total_seconds()

    # ----- Augment sourcing envelope with targeting params (for sourcing_neutrality) -----
    sourcing_env = state.envelopes_by_step.get("sourcing")
    targeting = fx.sourcing_targeting_params(with_violation=inject_violation)
    if sourcing_env and sourcing_env.artifacts_registry:
        _attach_targeting_to_prov(state.prov, "art-sourcing-decision", targeting)

    # ----- Build augmented envelope for attestation-bearing audits -----
    decision_support_env = state.envelopes_by_step.get("decision_support")
    augmented_env = decision_support_env
    if decision_support_env is not None:
        augmented_env, _ = _augment_with_attestations(
            decision_support_env, with_violation=inject_violation,
        )

    # ----- Audit checkpoints -----
    procurement_audit = _run_procurement_audit(state, augmented_envelope=augmented_env) \
        if augmented_env else {"checks": [], "overall_passed": False}
    inflight_audit = _run_inflight_audit(state, augmented_envelope=augmented_env) \
        if augmented_env else {"checks": [], "overall_passed": False}

    audit = HiringAuditResult(
        procurement=procurement_audit,
        inflight=inflight_audit,
        overall_passed=(
            procurement_audit.get("overall_passed", False)
            and inflight_audit.get("overall_passed", False)
        ),
    )

    # ----- Persist outputs -----
    for step, env in state.envelopes_by_step.items():
        (envelope_dir / f"{step}.json").write_text(
            json.dumps(env.to_jsonld(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if augmented_env is not None:
        (envelope_dir / "decision_support_augmented.json").write_text(
            json.dumps(augmented_env.to_jsonld(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    for step, blob in state.raw_outputs_by_step.items():
        (diff_dir / f"{step}_before.json").write_text(blob, encoding="utf-8")
    for step, blob in state.forwarded_outputs_by_step.items():
        (diff_dir / f"{step}_after.json").write_text(blob, encoding="utf-8")

    (prov_dir / "hiring.ttl").write_text(
        state.prov.serialize("turtle"), encoding="utf-8",
    )

    (audit_dir / "procurement.json").write_text(
        json.dumps(procurement_audit, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (audit_dir / "inflight.json").write_text(
        json.dumps(inflight_audit, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    metrics["context_id"] = context_id
    metrics["steps"] = state.step_order
    # Two composed pipelines: report both stages so a reviewer can see the
    # raw→semantic transition at the parsing handoff.
    metrics["pipeline_forwarding_policies"] = {
        "sourcing_stage": state.raw_enforcer.policy.value,
        "decision_stage": state.sem_enforcer.policy.value,
    }
    metrics["procurement_passed"] = procurement_audit.get("overall_passed", False)
    metrics["inflight_passed"] = inflight_audit.get("overall_passed", False)
    metrics["overall_passed"] = audit.overall_passed
    metrics["total_ms"] = (_time.perf_counter() - t_total) * 1000

    (output_root / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8",
    )
    return metrics


# ---------------------------------------------------------------------------
# Cohort entry point: run the pipeline N times and run the corpus audit
# ---------------------------------------------------------------------------

def run_hiring_cohort(
    *,
    output_root: Path = OUTPUT_ROOT,
    **_unused: Any,  # accepts inject_violation/n_receipts for parity with run_hiring_pipeline
) -> dict:
    """Build a corpus by re-running the in-memory envelope construction N times.

    Uses the deterministic mock LLM path (we don't call N LLM invocations);
    the goal is to feed ``feature_usage_census``, ``four_fifths_ratio``, and
    ``verify_incident_attestation`` from the same ``_verifiers`` module the
    paper-gating suite already uses.
    """
    output_root.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    candidates = fx.cohort_candidates()

    envelopes: list[Envelope] = []
    for i, c in enumerate(candidates):
        # The receipt's discriminating signal is the experience_band in the
        # payload; the index ``i`` salts the artifact content_hash so each
        # receipt has a distinct one.
        env = (
            EnvelopeBuilder()
            .set_producer(fx.PRODUCERS["screening"])
            .set_scope("hiring_cohort_screening_to_ranking")
            .set_risk_level(RiskLevel.HIGH)
            .set_human_oversight(True)
            .set_semantic_payload([{
                "candidate_id": c.candidate_id,
                "experience_band": c.experience_band,
                "skills_overlap": round(c.skills_overlap, 3),
                "advanced_to_recruiter": c.advanced_to_recruiter,
            }])
            .add_decision_influence(
                agent="screening-agent",
                categories=list(fx.SCREENING_WEIGHTS.keys()),
                influence_weights=dict(fx.SCREENING_WEIGHTS),
                confidence=0.85,
                abstraction_level=AbstractionLevel.SITUATION,
                temporal_scope=TemporalScope.HISTORICAL,
            )
            .add_artifact(
                artifact_id=f"art-rank-{c.candidate_id}",
                artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
                content_hash="sha256:" + ("0" * 60) + f"{i:04d}",
                model="screener-v1.4",
                data_governance_attestation_ref="data-gov:role-fam-swe-2026Q1",
                data_governance_attestation_signer=fx.DPO_SIGNER,
            )
            .sign(fx.COMPLIANCE_SIGNER)
            .build()
        )
        envelopes.append(env)

    censuses = feature_usage_census(envelopes,
                                    handoff_filter="hiring_cohort_screening_to_ranking")
    four_fifths = four_fifths_ratio(
        envelopes,
        group_attribute="experience_band",
        protected_value=">15y",
        reference_value="5-10y",
        advancement_predicate=lambda e: bool(
            e.semantic_payload[0].get("advanced_to_recruiter", False),
        ),
    )

    incidents_graph = PROVGraph("ctx-hiring-incidents")
    for ev in fx.suspension_events():
        incidents_graph.add_activity(
            ev.suspension_id, "Model suspension",
            started_at=ev.started_at.isoformat(),
            ended_at=(ev.started_at + timedelta(hours=1)).isoformat(),
        )
        incidents_graph.set_entity_attribute(ev.suspension_id, "kind", "suspension")
        if ev.notification_id and ev.notification_offset_days is not None:
            notif_dt = ev.started_at + timedelta(days=ev.notification_offset_days)
            incidents_graph.add_activity(
                ev.notification_id, "Art. 73 notification",
                started_at=notif_dt.isoformat(),
                ended_at=(notif_dt + timedelta(hours=1)).isoformat(),
            )
            incidents_graph.set_entity_attribute(
                ev.notification_id, "kind", "art73_notification",
            )
            incidents_graph.was_informed_by(ev.notification_id, ev.suspension_id)

    incident_audit = verify_incident_attestation(incidents_graph)

    summary = {
        "corpus_size": len(envelopes),
        "feature_usage_census": [c.to_dict() for c in censuses],
        "four_fifths": four_fifths.to_dict(),
        "incident_attestation": {
            "passed": incident_audit.passed,
            "message": incident_audit.message,
            "evidence": incident_audit.evidence,
        },
    }
    (AUDIT_DIR / "cohort.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return summary


__all__ = [
    "HiringFlowState",
    "make_task_callback",
    "run_hiring_pipeline",
    "run_hiring_cohort",
]

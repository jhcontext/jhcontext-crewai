"""Offline deterministic generator for the Benefits A3I scenario.

Produces:
  - raw-forward pipeline envelopes (intake + decision; no semantic extractor)
  - semantic-forward pipeline envelopes (intake + extractor + decision)
  - a PROV graph that includes per-statement child entities for the semantic
    layer so the citizen SPARQL queries can traverse the interpretation /
    situation layers structurally

Does NOT require any LLM credentials. Useful for fast verification, fixtures,
and the side-by-side citizen-query demo.

Output: <out_dir>/benefits_a3i_simulate_envelopes.json (both pipelines)
        <out_dir>/benefits_a3i_simulate_prov.ttl

After running, use ``python -m agent.scenarios.benefits_a3i.citizen_query``
to run the four SPARQL queries against the produced graph.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from jhcontext.builder import EnvelopeBuilder
from jhcontext.models import (
    Artifact,
    ArtifactType,
    ForwardingPolicy,
    RiskLevel,
)
from jhcontext.prov import PROVGraph

from agent.crews.benefits_a3i.lib import (
    benefits_eligibility_statement,
    TIER_2_THRESHOLD_EUR,
)

# ── Default toeslagenaffaire-style case ──
DEFAULT_CASE = {
    "claim_id": "claim-tslg-2024-04217",
    "citizen_id": "cit-anonym-9b3f",
    "income_eur": 42000,
    "current_tier": "tier_1",
    "requested_tier": "tier_2",
    "year": 2024,
}

CONTEXT_ID = "ctx-bnf-a3i-04217"

# DIDs
DID_INTAKE = "did:gov:a3i-intake-agent"
DID_EXTRACTOR = "did:gov:a3i-semantic-extractor"
DID_DECISION = "did:gov:a3i-decision-agent"
DID_SYSTEM = "did:gov:a3i-system"

# Artefact IDs (referenced by the SPARQL queries)
ART_INTAKE = "art-intake"
ART_EXTRACTOR = "art-extractor"
ART_DECISION = "art-decision"

# Activity IDs (referenced by the SPARQL queries)
ACT_INTAKE = "act-intake"
ACT_EXTRACTOR = "act-extractor"
ACT_DECISION = "act-decision"


def _h(payload_bytes: bytes) -> str:
    return hashlib.sha256(payload_bytes).hexdigest()


def build_raw_forward_envelopes(case: dict) -> list[dict]:
    """Two-task raw-forward pipeline: intake → decision."""
    payload = benefits_eligibility_statement(**case)
    raw_payload_doc = {
        "@model": "UserML",
        "layers": {"observation": payload["observation"]},
    }
    raw_payload_bytes = json.dumps(raw_payload_doc, sort_keys=True).encode()

    intake_env = (
        EnvelopeBuilder()
        .set_producer(DID_INTAKE)
        .set_scope("benefits.eligibility_explanation")
        .set_risk_level(RiskLevel.HIGH)
        .set_human_oversight(True)
        .set_forwarding_policy(ForwardingPolicy.RAW_FORWARD)
        .set_semantic_payload([raw_payload_doc])
        .add_artifact(
            artifact_id=ART_INTAKE,
            artifact_type=ArtifactType.TOKEN_SEQUENCE,
            content_hash=_h(raw_payload_bytes),
            model="deterministic-simulate",
            deterministic=True,
        )
        .build()
    )

    raw_decision_doc = {
        "@model": "UserML",
        "layers": {
            "application": [
                {
                    "predicate": "citizen_explanation",
                    "object": "Your claim was reduced. See the cited sources for the policy basis.",
                },
                {
                    "predicate": "cited_sources",
                    "object": [
                        "Child Benefit Eligibility Regulation 2024",
                        "Income Threshold Guidance §4.2",
                        "Benefits Appeals Procedure",
                    ],
                },
            ]
        },
    }
    raw_decision_bytes = json.dumps(raw_decision_doc, sort_keys=True).encode()

    decision_env = (
        EnvelopeBuilder()
        .set_producer(DID_DECISION)
        .set_scope("benefits.eligibility_explanation")
        .set_risk_level(RiskLevel.HIGH)
        .set_human_oversight(True)
        .set_forwarding_policy(ForwardingPolicy.RAW_FORWARD)
        .set_semantic_payload([raw_decision_doc])
        .add_artifact(
            artifact_id=ART_DECISION,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            content_hash=_h(raw_decision_bytes),
            model="deterministic-simulate",
            deterministic=True,
        )
        .set_passed_artifact(ART_DECISION)
        .build()
    )

    return [intake_env.to_jsonld(), decision_env.to_jsonld()]


def build_semantic_forward_envelopes(case: dict) -> list[dict]:
    """Three-task semantic-forward pipeline: intake → extractor → decision."""
    full_payload = benefits_eligibility_statement(**case)

    obs_doc = {"@model": "UserML", "layers": {"observation": full_payload["observation"]}}
    obs_bytes = json.dumps(obs_doc, sort_keys=True).encode()

    intake_env = (
        EnvelopeBuilder()
        .set_producer(DID_INTAKE)
        .set_scope("benefits.eligibility_explanation")
        .set_risk_level(RiskLevel.HIGH)
        .set_human_oversight(True)
        .set_forwarding_policy(ForwardingPolicy.SEMANTIC_FORWARD)
        .set_semantic_payload([obs_doc])
        .add_artifact(
            artifact_id=ART_INTAKE,
            artifact_type=ArtifactType.TOKEN_SEQUENCE,
            content_hash=_h(obs_bytes),
            model="deterministic-simulate",
            deterministic=True,
        )
        .build()
    )

    interp_doc = {
        "@model": "UserML",
        "layers": {
            "interpretation": full_payload["interpretation"],
            "situation": full_payload["situation"],
        },
    }
    interp_bytes = json.dumps(interp_doc, sort_keys=True).encode()

    extractor_env = (
        EnvelopeBuilder()
        .set_producer(DID_EXTRACTOR)
        .set_scope("benefits.eligibility_explanation")
        .set_risk_level(RiskLevel.HIGH)
        .set_human_oversight(True)
        .set_forwarding_policy(ForwardingPolicy.SEMANTIC_FORWARD)
        .set_semantic_payload([interp_doc])
        .add_artifact(
            artifact_id=ART_EXTRACTOR,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            content_hash=_h(interp_bytes),
            model="deterministic-simulate",
            deterministic=True,
        )
        .set_passed_artifact(ART_EXTRACTOR)
        .build()
    )

    app_doc = {"@model": "UserML", "layers": {"application": full_payload["application"]}}
    app_bytes = json.dumps(app_doc, sort_keys=True).encode()

    decision_env = (
        EnvelopeBuilder()
        .set_producer(DID_DECISION)
        .set_scope("benefits.eligibility_explanation")
        .set_risk_level(RiskLevel.HIGH)
        .set_human_oversight(True)
        .set_forwarding_policy(ForwardingPolicy.SEMANTIC_FORWARD)
        .set_semantic_payload([app_doc])
        .add_artifact(
            artifact_id=ART_DECISION,
            artifact_type=ArtifactType.SEMANTIC_EXTRACTION,
            content_hash=_h(app_bytes),
            model="deterministic-simulate",
            deterministic=True,
        )
        .set_passed_artifact(ART_DECISION)
        .build()
    )

    return [
        intake_env.to_jsonld(),
        extractor_env.to_jsonld(),
        decision_env.to_jsonld(),
    ]


def build_prov_graph(case: dict) -> PROVGraph:
    """Build a PROV graph for the semantic-forward pipeline.

    Per-statement child entities are created for the interpretation and
    situation layers so each statement is its own PROV.Entity carrying
    jh:semantic_layer / jh:semantic_predicate / jh:semantic_object /
    jh:semantic_confidence triples. wasDerivedFrom edges link
    decision → interpretations → observations.
    """
    prov = PROVGraph(context_id=CONTEXT_ID)

    # Agents + crew
    prov.add_crew(crew_id="crew:benefits-a3i", label="A3I Benefits Pipeline")
    prov.add_agent(agent_id=DID_INTAKE, label="A3I Intake Agent")
    prov.add_agent(agent_id=DID_EXTRACTOR, label="A3I Semantic Extractor")
    prov.add_agent(agent_id=DID_DECISION, label="A3I Decision Agent")
    for did in (DID_INTAKE, DID_EXTRACTOR, DID_DECISION):
        prov.acted_on_behalf_of(did, "crew:benefits-a3i")

    # Activities
    prov.add_activity(activity_id=ACT_INTAKE, label="Intake observation")
    prov.add_activity(activity_id=ACT_EXTRACTOR, label="Semantic extraction")
    prov.add_activity(activity_id=ACT_DECISION, label="Citizen-facing decision")

    # Parent artefacts
    prov.add_entity(entity_id=ART_INTAKE, label="Intake observation artefact")
    prov.add_entity(entity_id=ART_EXTRACTOR, label="Semantic extractor artefact")
    prov.add_entity(entity_id=ART_DECISION, label="Decision artefact")

    prov.was_generated_by(ART_INTAKE, ACT_INTAKE)
    prov.was_generated_by(ART_EXTRACTOR, ACT_EXTRACTOR)
    prov.was_generated_by(ART_DECISION, ACT_DECISION)

    prov.used(ACT_EXTRACTOR, ART_INTAKE)
    prov.used(ACT_DECISION, ART_EXTRACTOR)

    prov.was_associated_with(ACT_INTAKE, DID_INTAKE)
    prov.was_associated_with(ACT_EXTRACTOR, DID_EXTRACTOR)
    prov.was_associated_with(ACT_DECISION, DID_DECISION)

    prov.was_derived_from(ART_EXTRACTOR, ART_INTAKE)
    prov.was_derived_from(ART_DECISION, ART_EXTRACTOR)

    full_payload = benefits_eligibility_statement(**case)

    # Per-statement child entities for OBSERVATIONS (needed by the
    # counterfactual query so each interpretation can be linked back to its
    # originating observation).
    obs_stmt_ids: list[str] = []
    for idx, stmt in enumerate(full_payload.get("observation", []), start=1):
        mp = stmt["mainpart"]
        sid = f"stmt-obs-{idx}"
        obs_stmt_ids.append(sid)
        prov.add_entity(entity_id=sid, label=f"Observation statement {idx}")
        prov.set_entity_attribute(sid, "semantic_layer", "observation")
        prov.set_entity_attribute(sid, "semantic_predicate", mp["predicate"])
        prov.set_entity_attribute(sid, "semantic_object", str(mp["object"]))
        prov.was_derived_from(sid, ART_INTAKE)

    # Per-statement child entities for INTERPRETATIONS — these are the
    # semantic claims that the semantic_claims SPARQL query returns.
    for idx, stmt in enumerate(full_payload.get("interpretation", []), start=1):
        mp = stmt["mainpart"]
        sid = f"stmt-interp-{idx}"
        prov.add_entity(entity_id=sid, label=f"Interpretation statement {idx}")
        prov.set_entity_attribute(sid, "semantic_layer", "interpretation")
        prov.set_entity_attribute(sid, "semantic_predicate", mp["predicate"])
        prov.set_entity_attribute(sid, "semantic_object", str(mp["object"]))
        conf = stmt.get("explanation", {}).get("confidence")
        if conf is not None:
            prov.set_entity_attribute(sid, "semantic_confidence", str(conf))
        prov.was_derived_from(sid, ART_EXTRACTOR)
        # Each interpretation depends on all observations (worked-example fact)
        for obs_sid in obs_stmt_ids:
            prov.was_derived_from(sid, obs_sid)
        # Decision is derived from each interpretation (this is what makes the
        # reasoning_chain query non-trivial)
        prov.was_derived_from(ART_DECISION, sid)

    # Per-statement child entities for SITUATIONS
    for idx, stmt in enumerate(full_payload.get("situation", []), start=1):
        mp = stmt["mainpart"]
        sid = f"stmt-sit-{idx}"
        prov.add_entity(entity_id=sid, label=f"Situation statement {idx}")
        prov.set_entity_attribute(sid, "semantic_layer", "situation")
        prov.set_entity_attribute(sid, "semantic_predicate", mp["predicate"])
        prov.set_entity_attribute(sid, "semantic_object", str(mp["object"]))
        prov.was_derived_from(sid, ART_EXTRACTOR)
        prov.was_derived_from(ART_DECISION, sid)

    return prov


def run_simulation(case: dict | None = None, out_dir: Path | None = None) -> dict:
    case = case or DEFAULT_CASE
    out_dir = out_dir or Path("./out/benefits_a3i_simulate")
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = build_raw_forward_envelopes(case)
    semantic = build_semantic_forward_envelopes(case)
    prov = build_prov_graph(case)

    envelopes_path = out_dir / "benefits_a3i_simulate_envelopes.json"
    envelopes_path.write_text(
        json.dumps(
            {
                "case": case,
                "context_id": CONTEXT_ID,
                "raw_forward_pipeline": raw,
                "semantic_forward_pipeline": semantic,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            default=str,
        )
    )

    prov_path = out_dir / "benefits_a3i_simulate_prov.ttl"
    prov_path.write_text(prov.serialize("turtle"))

    print(f"[Benefits A3I simulate] envelopes -> {envelopes_path}")
    print(f"[Benefits A3I simulate] PROV      -> {prov_path}")
    print(
        "[Benefits A3I simulate] Run: python -m agent.scenarios.benefits_a3i.citizen_query"
    )
    return {
        "envelopes_path": str(envelopes_path),
        "prov_path": str(prov_path),
        "context_id": CONTEXT_ID,
    }


if __name__ == "__main__":
    run_simulation()

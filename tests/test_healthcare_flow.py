"""Healthcare composed-pipeline tests.

The cardiac-triage workflow is two composed pipelines (PAC-AI mixed-mode):

  raw_pipeline (raw_forward)       : sensor -> ontology_classification
  semantic_pipeline (semantic_fwd) : triage -> allocation

These tests are deterministic and need no ANTHROPIC_API_KEY: they assert
(a) the per-stage forwarding-policy wiring in the crew task configs, and
(b) the SDK composition contract the flow relies on (a raw_forward enforcer
and a semantic_forward enforcer accept only their own stage's envelopes, and
filter_output strips non-semantic fields only on the semantic side).

A live end-to-end flow run is exercised by test_healthcare_flow_live, which is
skipped unless RUN_LIVE_HEALTHCARE=1 (it needs an LLM + the backend API).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from jhcontext import (
    EnvelopeBuilder,
    ForwardingEnforcer,
    ForwardingPolicy,
    RiskLevel,
)
from jhcontext.forwarding import ForwardingPolicyViolation

import agent.crews.healthcare.crew as hc

CONFIG = Path(hc.__file__).parent / "config"


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text())


def _envelope(policy: ForwardingPolicy):
    """Minimal signed envelope declaring the given forwarding policy."""
    return (
        EnvelopeBuilder()
        .set_producer("did:hospital:test-agent")
        .set_scope("healthcare_treatment_recommendation")
        .set_risk_level(RiskLevel.HIGH)
        .set_human_oversight(True)
        .set_forwarding_policy(policy)
        .set_semantic_payload([{"@model": "UserML", "layers": {"interpretation": []}}])
        .build()
    )


# ---------------------------------------------------------------- wiring ----

def test_raw_crew_exposes_sensor_then_ontology():
    crew = hc.HealthcareRawCrew()
    assert hasattr(crew, "sensor_task")
    assert hasattr(crew, "ontology_classification_task")
    assert hasattr(crew, "sensor_agent")
    assert hasattr(crew, "ontology_agent")


def test_semantic_crew_exposes_triage_then_allocation():
    crew = hc.HealthcareSemanticCrew()
    assert hasattr(crew, "triage_task")
    assert hasattr(crew, "allocation_task")
    assert hasattr(crew, "triage_agent")
    assert hasattr(crew, "allocation_agent")


def test_raw_stage_tasks_declare_raw_forward():
    tasks = _load("raw_tasks.yaml")
    for name, artifact in (("sensor_task", "art-sensor"),
                           ("ontology_classification_task", "art-ontology")):
        desc = tasks[name]["description"]
        assert 'forwarding_policy="raw_forward"' in desc, name
        assert artifact in desc, name


def test_semantic_stage_tasks_declare_semantic_forward():
    tasks = _load("semantic_tasks.yaml")
    for name, artifact in (("triage_task", "art-triage"),
                           ("allocation_task", "art-allocation")):
        desc = tasks[name]["description"]
        assert 'forwarding_policy="semantic_forward"' in desc, name
        assert artifact in desc, name


def test_semantic_stage_consumes_upstream_payload():
    """The first semantic task reads the raw pipeline's terminal artifact."""
    tasks = _load("semantic_tasks.yaml")
    assert "{upstream_semantic_payload}" in tasks["triage_task"]["description"]


def test_four_agents_defined():
    agents = {**_load("raw_agents.yaml"), **_load("semantic_agents.yaml")}
    assert set(agents) == {
        "sensor_agent", "ontology_agent", "triage_agent", "allocation_agent",
    }


# ----------------------------------------------------- composition contract --

def test_each_stage_enforcer_accepts_only_its_own_policy():
    raw = ForwardingEnforcer(ForwardingPolicy.RAW_FORWARD)
    sem = ForwardingEnforcer(ForwardingPolicy.SEMANTIC_FORWARD)
    raw_env = _envelope(ForwardingPolicy.RAW_FORWARD)
    sem_env = _envelope(ForwardingPolicy.SEMANTIC_FORWARD)

    # Within its own stage each enforcer resolves cleanly.
    assert raw.resolve(raw_env) == ForwardingPolicy.RAW_FORWARD
    assert sem.resolve(sem_env) == ForwardingPolicy.SEMANTIC_FORWARD

    # Cross-stage envelopes are rejected — this is why the flow must SWAP the
    # enforcer per pipeline rather than use one enforcer for both.
    with pytest.raises(ForwardingPolicyViolation):
        sem.resolve(raw_env)
    with pytest.raises(ForwardingPolicyViolation):
        raw.resolve(sem_env)


def test_semantic_boundary_strips_non_semantic_fields():
    sem = ForwardingEnforcer(ForwardingPolicy.SEMANTIC_FORWARD)
    sem_env = _envelope(ForwardingPolicy.SEMANTIC_FORWARD)
    forwarded = sem.filter_output(sem_env, ForwardingPolicy.SEMANTIC_FORWARD)
    assert "semantic_payload" in forwarded
    assert "artifacts_registry" not in forwarded
    assert "compliance" not in forwarded


def test_raw_boundary_forwards_full_envelope():
    raw = ForwardingEnforcer(ForwardingPolicy.RAW_FORWARD)
    raw_env = _envelope(ForwardingPolicy.RAW_FORWARD)
    forwarded = raw.filter_output(raw_env, ForwardingPolicy.RAW_FORWARD)
    # Raw stage carries the full envelope across the handoff.
    assert "semantic_payload" in forwarded
    assert "compliance" in forwarded


# ------------------------------------------------------------- live (opt) ---

@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_HEALTHCARE") != "1",
    reason="live flow needs an LLM + backend API; set RUN_LIVE_HEALTHCARE=1",
)
def test_healthcare_flow_live(tmp_path):
    from agent.flows.healthcare_flow import HealthcareFlow

    flow = HealthcareFlow()
    flow.kickoff()
    envelopes = flow.state.get("_task_envelopes", [])
    # sensor, ontology (raw) + triage, allocation (semantic) = 4 task envelopes.
    assert len(envelopes) >= 4

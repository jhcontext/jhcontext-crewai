"""End-to-end test of the hiring multi-agent flow with the deterministic mock LLM.

No ``ANTHROPIC_API_KEY`` required: ``MockHiringLLM`` returns canned
``FlatEnvelope`` JSON keyed by which task is running, so the flow is fully
reproducible offline. The test asserts:

  * all six handoffs ran,
  * the SDK ``ForwardingEnforcer`` flipped the semantic boundary on,
  * the boundary stripped the artifacts list out of downstream payloads
    (the forwarded blob contains ``semantic_payload`` only),
  * procurement and in-flight audit checkpoints both PASS by default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Ensure the flow uses the offline mock LLM regardless of the test environment.
os.environ.setdefault("HIRING_USE_MOCK_LLM", "1")
os.environ.setdefault("ANTHROPIC_API_KEY", "")  # force mock-LLM auto-detect path

from agent.flows.hiring_flow import run_hiring_cohort, run_hiring_pipeline


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    return tmp_path / "hiring"


def test_hiring_pipeline_offline_passes_default(output_dir: Path) -> None:
    metrics = run_hiring_pipeline(
        inject_violation=False,
        use_mock_llm=True,
        output_root=output_dir,
    )

    # All six handoffs fired in order.
    assert metrics["steps"] == [
        "sourcing", "parsing", "screening",
        "interview", "ranking", "decision_support",
    ], metrics["steps"]

    # Two composed pipelines: raw sourcing → semantic decision stage.
    assert metrics["pipeline_forwarding_policies"] == {
        "sourcing_stage": "raw_forward",
        "decision_stage": "semantic_forward",
    }

    # Both audit checkpoints pass with default fixtures.
    assert metrics["procurement_passed"], "procurement audit should PASS"
    assert metrics["inflight_passed"], "in-flight audit should PASS"


def test_forwarding_diff_strips_artifacts_at_boundary(output_dir: Path) -> None:
    """After the boundary, the forwarded blob carries semantic_payload ONLY."""
    run_hiring_pipeline(
        inject_violation=False,
        use_mock_llm=True,
        output_root=output_dir,
    )

    diff_dir = output_dir / "forwarding_diff"
    # Pick any post-boundary step (parsing onwards is semantic_forward).
    after = json.loads((diff_dir / "screening_after.json").read_text())
    before = json.loads((diff_dir / "screening_before.json").read_text())

    # The "before" snapshot is the full envelope; "after" is the forwarded
    # view exposed to the next agent.
    assert "artifacts_registry" in before
    assert "semantic_payload" in after
    assert "artifacts_registry" not in after, (
        "Semantic-Forward must strip artifacts_registry from the forwarded view"
    )


def test_inflight_violation_fails_temporal_oversight(output_dir: Path) -> None:
    """Rubber-stamp recruiter review trips verify_temporal_oversight."""
    metrics = run_hiring_pipeline(
        inject_violation=True,
        use_mock_llm=True,
        output_root=output_dir,
    )
    # Recruiter review is collapsed to ~7.5 s under violation injection
    # (0.025 min/candidate * 60 s * 5 candidates).
    assert metrics["recruiter_review_seconds"] < 300.0
    assert metrics["inflight_passed"] is False


def test_cohort_seeded_disparity_fails_four_fifths(output_dir: Path) -> None:
    summary = run_hiring_cohort(output_root=output_dir)
    ff = summary["four_fifths"]
    assert summary["corpus_size"] == 312
    assert ff["ratio"] == pytest.approx(0.6, rel=1e-6)
    assert ff["passed"] is False  # 0.6 < 0.8 -> disparate impact
    # Two suspensions: one notified within 15 days, one missing -> overall fail.
    assert summary["incident_attestation"]["passed"] is False

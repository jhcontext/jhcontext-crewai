"""Post-run validation script for PAC-AI protocol scenarios.

Reads ``output/`` directory after a prior ``python -m agent.run --scenario all``
and produces structured results matching the AIS 2026 paper's tables.

Usage::

    python -m agent.validate
    # or via run.py:
    python -m agent.run --validate
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from jhcontext import PROVGraph
from jhcontext.audit import (
    verify_negative_proof,
    verify_workflow_isolation,
)

from agent.ontologies.healthcare import HEALTHCARE_PREDICATES
from agent.ontologies.education import EDUCATION_PREDICATES
from agent.ontologies.recommendation import RECOMMENDATION_PREDICATES
from agent.ontologies.validator import validate_semantic_payload

OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ── Helpers ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_prov(path: Path) -> PROVGraph | None:
    if not path.exists():
        return None
    prov = PROVGraph(context_id=path.stem)
    prov._graph.parse(data=path.read_text(), format="turtle")
    return prov


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _count_agents(prov: PROVGraph) -> int:
    """Count prov:Agent instances in the graph."""
    from rdflib.namespace import RDF, PROV as PROV_NS
    return len(list(prov._graph.subjects(RDF.type, PROV_NS.Agent)))


def _extract_semantic_payload(envelope: dict) -> dict | None:
    """Extract semantic_payload from an envelope dict."""
    if not envelope:
        return None
    payload = envelope.get("semantic_payload")
    if isinstance(payload, list) and payload:
        # Check if first element is a UserML payload
        for item in payload:
            if isinstance(item, dict) and item.get("@model") == "UserML":
                return item
    elif isinstance(payload, dict) and payload.get("@model") == "UserML":
        return payload
    return None


# ── Scenario validators ──────────────────────────────────────────────

def validate_healthcare() -> dict[str, Any]:
    """Validate healthcare scenario outputs."""
    results: dict[str, Any] = {"scenario": "healthcare", "checks": {}, "metrics": {}}

    envelope = _load_json(OUTPUT_DIR / "healthcare_envelope.json")
    prov = _load_prov(OUTPUT_DIR / "healthcare_prov.ttl")
    audit = _load_json(OUTPUT_DIR / "healthcare_audit.json")
    metrics = _load_json(OUTPUT_DIR / "healthcare_metrics.json")

    # Table 1: Artifact characteristics
    results["metrics"]["envelope_bytes"] = _file_size(OUTPUT_DIR / "healthcare_envelope.json")
    results["metrics"]["prov_bytes"] = _file_size(OUTPUT_DIR / "healthcare_prov.ttl")

    if prov:
        entities = prov.get_all_entities()
        sequence = prov.get_temporal_sequence()
        results["metrics"]["entity_count"] = len(entities)
        results["metrics"]["activity_count"] = len(sequence)
        results["metrics"]["agent_count"] = _count_agents(prov)
    else:
        results["checks"]["prov_exists"] = {"passed": False, "message": "PROV graph file missing"}

    if envelope:
        artifacts = envelope.get("artifacts_registry", [])
        results["metrics"]["artifact_count"] = len(artifacts)

        # Check forwarding policy
        compliance = envelope.get("compliance", {})
        results["checks"]["risk_level"] = {
            "passed": compliance.get("risk_level") == "high",
            "value": compliance.get("risk_level"),
        }
        results["checks"]["forwarding_policy"] = {
            "passed": compliance.get("forwarding_policy") in ("semantic_forward", "semantic-forward"),
            "value": compliance.get("forwarding_policy"),
        }

        # Semantic payload conformance
        payload = _extract_semantic_payload(envelope)
        if payload:
            valid, violations = validate_semantic_payload(payload, HEALTHCARE_PREDICATES)
            results["checks"]["semantic_conformance"] = {
                "passed": valid,
                "violations": violations,
            }
        else:
            results["checks"]["semantic_conformance"] = {
                "passed": False,
                "message": "No UserML payload found in envelope",
            }
    else:
        results["checks"]["envelope_exists"] = {"passed": False, "message": "Envelope file missing"}

    # Programmatic audit results (from the flow)
    if audit:
        programmatic = audit.get("programmatic_checks", {})
        if programmatic:
            for check_result in programmatic.get("results", []):
                results["checks"][check_result["check_name"]] = {
                    "passed": check_result["passed"],
                    "evidence": check_result.get("evidence", {}),
                    "message": check_result.get("message", ""),
                }
        results["checks"]["overall_passed"] = {
            "passed": audit.get("overall_passed", False),
        }

    # Performance metrics
    if metrics:
        results["metrics"]["performance"] = metrics

    return results


def validate_education() -> dict[str, Any]:
    """Validate education scenario outputs."""
    results: dict[str, Any] = {"scenario": "education", "checks": {}, "metrics": {}}

    grading_envelope = _load_json(OUTPUT_DIR / "education_grading_envelope.json")
    grading_prov = _load_prov(OUTPUT_DIR / "education_grading_prov.ttl")
    equity_prov = _load_prov(OUTPUT_DIR / "education_equity_prov.ttl")
    audit = _load_json(OUTPUT_DIR / "education_audit.json")
    metrics = _load_json(OUTPUT_DIR / "education_grading_metrics.json")

    # Table 1: Artifact characteristics
    results["metrics"]["grading_envelope_bytes"] = _file_size(OUTPUT_DIR / "education_grading_envelope.json")
    results["metrics"]["grading_prov_bytes"] = _file_size(OUTPUT_DIR / "education_grading_prov.ttl")
    results["metrics"]["equity_prov_bytes"] = _file_size(OUTPUT_DIR / "education_equity_prov.ttl")

    if grading_prov:
        entities = grading_prov.get_all_entities()
        sequence = grading_prov.get_temporal_sequence()
        results["metrics"]["grading_entity_count"] = len(entities)
        results["metrics"]["grading_activity_count"] = len(sequence)
        results["metrics"]["grading_agent_count"] = _count_agents(grading_prov)

    if equity_prov:
        entities = equity_prov.get_all_entities()
        results["metrics"]["equity_entity_count"] = len(entities)

    # Re-run SDK audit functions on the output files
    if grading_prov and equity_prov:
        isolation = verify_workflow_isolation(grading_prov, equity_prov)
        results["checks"]["workflow_isolation"] = {
            "passed": isolation.passed,
            "evidence": isolation.evidence,
            "message": isolation.message,
        }

        negative = verify_negative_proof(
            prov=grading_prov,
            decision_entity_id="art-grading",
            excluded_artifact_types=["identity_data", "demographic", "biometric"],
        )
        results["checks"]["negative_proof"] = {
            "passed": negative.passed,
            "evidence": negative.evidence,
            "message": negative.message,
        }
    else:
        results["checks"]["prov_exists"] = {
            "passed": False,
            "message": "One or both PROV graph files missing",
        }

    # Semantic payload conformance
    if grading_envelope:
        payload = _extract_semantic_payload(grading_envelope)
        if payload:
            valid, violations = validate_semantic_payload(payload, EDUCATION_PREDICATES)
            results["checks"]["semantic_conformance"] = {
                "passed": valid,
                "violations": violations,
            }
        else:
            results["checks"]["semantic_conformance"] = {
                "passed": False,
                "message": "No UserML payload found in grading envelope",
            }

    # Flow audit results
    if audit:
        results["checks"]["audit_overall_passed"] = {
            "passed": audit.get("overall_passed", False),
        }

    # Performance metrics
    if metrics:
        results["metrics"]["performance"] = metrics

    return results


def validate_recommendation() -> dict[str, Any]:
    """Validate recommendation scenario outputs."""
    results: dict[str, Any] = {"scenario": "recommendation", "checks": {}, "metrics": {}}

    envelope = _load_json(OUTPUT_DIR / "recommendation_envelope.json")
    prov = _load_prov(OUTPUT_DIR / "recommendation_prov.ttl")
    metrics = _load_json(OUTPUT_DIR / "recommendation_metrics.json")

    # Table 1: Artifact characteristics
    results["metrics"]["envelope_bytes"] = _file_size(OUTPUT_DIR / "recommendation_envelope.json")
    results["metrics"]["prov_bytes"] = _file_size(OUTPUT_DIR / "recommendation_prov.ttl")

    if prov:
        entities = prov.get_all_entities()
        sequence = prov.get_temporal_sequence()
        results["metrics"]["entity_count"] = len(entities)
        results["metrics"]["activity_count"] = len(sequence)
        results["metrics"]["agent_count"] = _count_agents(prov)

    if envelope:
        artifacts = envelope.get("artifacts_registry", [])
        results["metrics"]["artifact_count"] = len(artifacts)

        # Check forwarding policy is raw_forward for LOW-risk
        compliance = envelope.get("compliance", {})
        results["checks"]["risk_level"] = {
            "passed": compliance.get("risk_level") == "low",
            "value": compliance.get("risk_level"),
        }
        results["checks"]["forwarding_policy"] = {
            "passed": compliance.get("forwarding_policy") in ("raw_forward", "raw-forward"),
            "value": compliance.get("forwarding_policy"),
        }

        # Semantic payload conformance
        payload = _extract_semantic_payload(envelope)
        if payload:
            valid, violations = validate_semantic_payload(payload, RECOMMENDATION_PREDICATES)
            results["checks"]["semantic_conformance"] = {
                "passed": valid,
                "violations": violations,
            }
        else:
            results["checks"]["semantic_conformance"] = {
                "passed": False,
                "message": "No UserML payload found in envelope",
            }
    else:
        results["checks"]["envelope_exists"] = {"passed": False, "message": "Envelope file missing"}

    # Performance metrics
    if metrics:
        results["metrics"]["performance"] = metrics

    return results


# ── Report formatting ────────────────────────────────────────────────

def _print_table_1(results: list[dict]) -> None:
    """Print Table 1: Artifact Characteristics."""
    print("\n" + "=" * 70)
    print("TABLE 1: Artifact Characteristics")
    print("=" * 70)
    header = f"{'Metric':<35} {'Healthcare':>10} {'Education':>10} {'Recommend':>10}"
    print(header)
    print("-" * 70)

    metric_keys = [
        ("envelope_bytes", "Envelope size (bytes)"),
        ("prov_bytes", "PROV graph size (bytes)"),
        ("entity_count", "Entity count"),
        ("activity_count", "Activity count"),
        ("agent_count", "Agent count"),
        ("artifact_count", "Artifact count"),
    ]

    for key, label in metric_keys:
        vals = []
        for r in results:
            m = r.get("metrics", {})
            # Education has prefixed keys
            if r["scenario"] == "education":
                v = m.get(f"grading_{key}", m.get(key, "—"))
            else:
                v = m.get(key, "—")
            vals.append(str(v) if v != "—" else "—")
        print(f"{label:<35} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")


def _print_table_2(results: list[dict]) -> None:
    """Print Table 2: Audit Results."""
    print("\n" + "=" * 70)
    print("TABLE 2: Audit Results")
    print("=" * 70)

    check_names = [
        "temporal_oversight",
        "integrity",
        "workflow_isolation",
        "negative_proof",
        "semantic_conformance",
        "risk_level",
        "forwarding_policy",
    ]

    header = f"{'Check':<30} {'Healthcare':>12} {'Education':>12} {'Recommend':>12}"
    print(header)
    print("-" * 70)

    for check in check_names:
        vals = []
        for r in results:
            c = r.get("checks", {}).get(check)
            if c is None:
                vals.append("n/a")
            elif c.get("passed"):
                vals.append("PASS")
            else:
                vals.append("FAIL")
        print(f"{check:<30} {vals[0]:>12} {vals[1]:>12} {vals[2]:>12}")


def _all_passed(results: list[dict]) -> bool:
    """Check if all non-n/a checks passed."""
    for r in results:
        for check_name, check in r.get("checks", {}).items():
            if isinstance(check, dict) and "passed" in check:
                if not check["passed"]:
                    return False
    return True


# ── Main ─────────────────────────────────────────────────────────────

def run_validation() -> int:
    """Run all scenario validations and print report.

    Returns 0 if all checks pass, 1 otherwise.
    """
    if not OUTPUT_DIR.exists():
        print(f"ERROR: Output directory {OUTPUT_DIR} does not exist.")
        print("Run scenarios first: python -m agent.run --scenario all")
        return 1

    output_files = list(OUTPUT_DIR.glob("*"))
    if not output_files:
        print(f"ERROR: No output files found in {OUTPUT_DIR}/")
        print("Run scenarios first: python -m agent.run --scenario all")
        return 1

    print("=" * 70)
    print("PAC-AI PROTOCOL VALIDATION REPORT")
    print("=" * 70)
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Files found: {len(output_files)}")

    results = []

    # Validate each scenario
    print("\nValidating healthcare scenario...")
    healthcare = validate_healthcare()
    results.append(healthcare)

    print("Validating education scenario...")
    education = validate_education()
    results.append(education)

    print("Validating recommendation scenario...")
    recommendation = validate_recommendation()
    results.append(recommendation)

    # Print tables
    _print_table_1(results)
    _print_table_2(results)

    # Overall result
    all_ok = _all_passed(results)
    print("\n" + "=" * 70)
    print(f"OVERALL: {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    print("=" * 70)

    # Save full report
    report = {
        "scenarios": results,
        "overall_passed": all_ok,
    }
    report_path = OUTPUT_DIR / "validation_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nFull report saved to: {report_path}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run_validation())

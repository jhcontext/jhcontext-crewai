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
from agent.ontologies.finance import FINANCE_PREDICATES
from agent.ontologies.validator import validate_semantic_payload

import agent.output_dir as _out


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

    envelope = _load_json(_out.current / "healthcare_envelope.json")
    prov = _load_prov(_out.current / "healthcare_prov.ttl")
    audit = _load_json(_out.current / "healthcare_audit.json")
    metrics = _load_json(_out.current / "healthcare_metrics.json")

    # Table 1: Artifact characteristics
    results["metrics"]["envelope_bytes"] = _file_size(_out.current / "healthcare_envelope.json")
    results["metrics"]["prov_bytes"] = _file_size(_out.current / "healthcare_prov.ttl")

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

    grading_envelope = _load_json(_out.current / "education_grading_envelope.json")
    grading_prov = _load_prov(_out.current / "education_grading_prov.ttl")
    equity_prov = _load_prov(_out.current / "education_equity_prov.ttl")
    audit = _load_json(_out.current / "education_audit.json")
    metrics = _load_json(_out.current / "education_grading_metrics.json")

    # Table 1: Artifact characteristics
    results["metrics"]["grading_envelope_bytes"] = _file_size(_out.current / "education_grading_envelope.json")
    results["metrics"]["grading_prov_bytes"] = _file_size(_out.current / "education_grading_prov.ttl")
    results["metrics"]["equity_prov_bytes"] = _file_size(_out.current / "education_equity_prov.ttl")

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

    envelope = _load_json(_out.current / "recommendation_envelope.json")
    prov = _load_prov(_out.current / "recommendation_prov.ttl")
    metrics = _load_json(_out.current / "recommendation_metrics.json")

    # Table 1: Artifact characteristics
    results["metrics"]["envelope_bytes"] = _file_size(_out.current / "recommendation_envelope.json")
    results["metrics"]["prov_bytes"] = _file_size(_out.current / "recommendation_prov.ttl")

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


def validate_finance() -> dict[str, Any]:
    """Validate finance scenario outputs."""
    results: dict[str, Any] = {"scenario": "finance", "checks": {}, "metrics": {}}

    envelope = _load_json(_out.current / "finance_envelope.json")
    credit_prov = _load_prov(_out.current / "finance_credit_prov.ttl")
    fair_lending_prov = _load_prov(_out.current / "finance_fair_lending_prov.ttl")
    audit = _load_json(_out.current / "finance_audit.json")
    metrics = _load_json(_out.current / "finance_metrics.json")

    # Table 1: Artifact characteristics
    results["metrics"]["envelope_bytes"] = _file_size(_out.current / "finance_envelopes.json")
    results["metrics"]["prov_bytes"] = _file_size(_out.current / "finance_credit_prov.ttl")
    results["metrics"]["fair_lending_prov_bytes"] = _file_size(_out.current / "finance_fair_lending_prov.ttl")

    if credit_prov:
        entities = credit_prov.get_all_entities()
        sequence = credit_prov.get_temporal_sequence()
        results["metrics"]["entity_count"] = len(entities)
        results["metrics"]["activity_count"] = len(sequence)
        results["metrics"]["agent_count"] = _count_agents(credit_prov)

    # Re-run SDK audit functions on the output files
    if credit_prov and fair_lending_prov:
        isolation = verify_workflow_isolation(credit_prov, fair_lending_prov)
        results["checks"]["workflow_isolation"] = {
            "passed": isolation.passed,
            "evidence": isolation.evidence,
            "message": isolation.message,
        }

        negative = verify_negative_proof(
            prov=credit_prov,
            decision_entity_id="art-credit-decision",
            excluded_artifact_types=["gender", "ethnicity", "marital_status", "nationality", "age", "religion"],
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

    if envelope:
        compliance = envelope.get("compliance", {})
        results["checks"]["risk_level"] = {
            "passed": compliance.get("risk_level") == "high",
            "value": compliance.get("risk_level"),
        }
        results["checks"]["forwarding_policy"] = {
            "passed": compliance.get("forwarding_policy") in ("semantic_forward", "semantic-forward"),
            "value": compliance.get("forwarding_policy"),
        }

        payload = _extract_semantic_payload(envelope)
        if payload:
            valid, violations = validate_semantic_payload(payload, FINANCE_PREDICATES)
            results["checks"]["semantic_conformance"] = {
                "passed": valid,
                "violations": violations,
            }

    # Flow audit results
    if audit:
        programmatic = audit.get("programmatic_checks", {})
        if programmatic:
            for check_result in programmatic.get("results", []):
                results["checks"][check_result["check_name"]] = {
                    "passed": check_result["passed"],
                    "evidence": check_result.get("evidence", {}),
                    "message": check_result.get("message", ""),
                }

        composite = audit.get("composite_compliance", {})
        results["checks"]["composite_compliance"] = {
            "passed": composite.get("all_passed", False),
        }

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
    scenarios = [r["scenario"] for r in results]
    col_width = 10
    header_cols = " ".join(f"{s[:10]:>{col_width}}" for s in scenarios)
    header = f"{'Metric':<35} {header_cols}"
    print(header)
    print("-" * (35 + (col_width + 1) * len(scenarios)))

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
        val_cols = " ".join(f"{v:>{col_width}}" for v in vals)
        print(f"{label:<35} {val_cols}")


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
        "composite_compliance",
    ]

    scenarios = [r["scenario"] for r in results]
    col_width = 12
    header_cols = " ".join(f"{s[:12]:>{col_width}}" for s in scenarios)
    header = f"{'Check':<30} {header_cols}"
    print(header)
    print("-" * (30 + (col_width + 1) * len(scenarios)))

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
        val_cols = " ".join(f"{v:>{col_width}}" for v in vals)
        print(f"{check:<30} {val_cols}")


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
    if not _out.current.exists():
        print(f"ERROR: Output directory {_out.current} does not exist.")
        print("Run scenarios first: python -m agent.run --scenario all")
        return 1

    output_files = list(_out.current.glob("*"))
    if not output_files:
        print(f"ERROR: No output files found in {_out.current}/")
        print("Run scenarios first: python -m agent.run --scenario all")
        return 1

    print("=" * 70)
    print("PAC-AI PROTOCOL VALIDATION REPORT")
    print("=" * 70)
    print(f"Output directory: {_out.current}")
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

    print("Validating finance scenario...")
    finance = validate_finance()
    results.append(finance)

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
    report_path = _out.current / "validation_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))

    # Generate human-readable summary
    summary_path = _out.current / "summary.md"
    summary_path.write_text(_generate_summary(results, all_ok))

    print(f"\nFull report: {report_path}")
    print(f"Summary:     {summary_path}")

    return 0 if all_ok else 1


def _generate_summary(results: list[dict], all_ok: bool) -> str:
    """Generate a human-readable summary.md for the run."""
    from datetime import datetime, timezone

    lines = [
        f"# PAC-AI Validation Run — {_out.current.name}",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Overall:** {'PASS' if all_ok else 'FAIL'}",
        "",
        "## Artifact Characteristics",
        "",
    ]

    scenario_names = [r["scenario"].capitalize() for r in results]
    lines.append("| Metric | " + " | ".join(scenario_names) + " |")
    lines.append("|--------" + "|---" * len(scenario_names) + "|")

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
            if r["scenario"] == "education":
                v = m.get(f"grading_{key}", m.get(key, "—"))
            else:
                v = m.get(key, "—")
            vals.append(str(v) if v != "—" else "—")
        lines.append("| " + label + " | " + " | ".join(vals) + " |")

    lines += [
        "",
        "## Audit Checks",
        "",
    ]
    lines.append("| Check | " + " | ".join(scenario_names) + " | What it verifies |")
    lines.append("|-------" + "|---" * len(scenario_names) + "|-----------------|")

    check_info = {
        "temporal_oversight": "Human reviewed source docs AFTER AI recommendation (Art. 14)",
        "integrity": "Envelope hash + signature match (tamper-evidence)",
        "workflow_isolation": "Zero shared artifacts between isolated workflows (Art. 13)",
        "negative_proof": "Protected data absent from decision PROV chain (Art. 13)",
        "semantic_conformance": "Semantic payload uses valid UserML predicates from domain ontology",
        "risk_level": "Envelope risk_level matches expected (high/low)",
        "forwarding_policy": "Envelope forwarding_policy matches expected (semantic/raw)",
        "composite_compliance": "All 4 compliance patterns verified (finance only)",
    }

    for check, description in check_info.items():
        vals = []
        for r in results:
            c = r.get("checks", {}).get(check)
            if c is None:
                vals.append("n/a")
            elif c.get("passed"):
                vals.append("PASS")
            else:
                vals.append("**FAIL**")
        lines.append("| " + check + " | " + " | ".join(vals) + " | " + description + " |")

    lines += [
        "",
        "## How to Read Results",
        "",
        "- **PASS** — the check succeeded against the protocol specification",
        "- **FAIL** — the check found a violation (see `validation_report.json` for details)",
        "- **n/a** — the check does not apply to this scenario",
        "",
        "### Key checks by scenario",
        "",
        "**Healthcare (Article 14 — Human Oversight):**",
        "- `temporal_oversight`: Verifies the physician accessed 4 source documents",
        "  (CT scan, treatment history, pathology, AI recommendation) AFTER the AI",
        "  generated its recommendation, with meaningful review duration (not rubber-stamping).",
        "- `integrity`: Verifies the envelope's cryptographic hash and signature are valid.",
        "",
        "**Education (Article 13 — Non-Discrimination):**",
        "- `workflow_isolation`: Verifies grading and equity workflows share zero PROV",
        "  entities — complete data isolation between identity and assessment.",
        "- `negative_proof`: Verifies no identity/demographic artifacts appear anywhere",
        "  in the grading dependency chain (recursive traversal).",
        "",
        "**Recommendation (LOW-risk):**",
        "- `risk_level=low` + `forwarding_policy=raw_forward`: Confirms LOW-risk",
        "  scenarios correctly use Raw-Forward (no Semantic-Forward constraint needed).",
        "",
        "**Finance (Annex III 5b — Composite Compliance):**",
        "- `temporal_oversight`: Credit officer reviewed income, employment, bureau report,",
        "  and AI recommendation AFTER AI generated its credit decision.",
        "- `negative_proof`: Protected attributes (gender, ethnicity, marital status,",
        "  nationality, age, religion) absent from credit decision PROV chain.",
        "- `workflow_isolation`: Fair lending workflow shares zero artifacts with credit pipeline.",
        "- `composite_compliance`: All 4 patterns (negative proof, temporal oversight,",
        "  workflow isolation, integrity) verified — first scenario to combine all patterns.",
        "",
        "### Semantic conformance",
        "",
        "This check verifies LLM agents produced semantic payloads in UserML format",
        "(`{\"@model\": \"UserML\", \"layers\": {...}}`) with valid domain predicates.",
        "Failures here mean the LLM output free-form JSON instead of the structured",
        "UserML format — the protocol still functions, but payloads are not formally",
        "typed. Use `FlatEnvelope` with `output_pydantic` to enforce stricter structure.",
        "",
        "## Files in This Run",
        "",
    ]

    for f in sorted(_out.current.glob("*")):
        if f.is_file() and f.name != "summary.md":
            lines.append(f"- `{f.name}` ({f.stat().st_size:,} bytes)")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(run_validation())

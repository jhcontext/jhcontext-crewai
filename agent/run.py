"""Entry point for running jhcontext-aws agent scenarios.

Usage:
    python -m agent.run --scenario healthcare
    python -m agent.run --scenario education
    python -m agent.run --scenario recommendation
    python -m agent.run --scenario all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def run_healthcare():
    """Run the healthcare human oversight scenario (Article 14).

    Demonstrates Semantic-Forward task chaining: a multi-task clinical
    crew (sensor → situation → decision) where each task outputs a full
    jhcontext Envelope and subsequent tasks consume ``semantic_payload``
    as canonical input.
    """
    from agent.flows.healthcare_flow import HealthcareFlow

    print("=" * 60)
    print("SCENARIO: Healthcare Human Oversight (EU AI Act Art. 14)")
    print("  Pattern: Semantic-Forward | Risk: HIGH")
    print("=" * 60)

    flow = HealthcareFlow()
    result = flow.kickoff()

    print("\n" + "=" * 60)
    print("Healthcare scenario complete.")
    print(f"Outputs in: {OUTPUT_DIR}/healthcare_*")
    return result


def run_education():
    """Run the education fair assessment scenario (Article 13).

    Runs three sub-flows:
    1. Grading workflow (identity-free)
    2. Equity reporting workflow (isolated)
    3. Audit workflow (verifies isolation)
    """
    from agent.flows.education_flow import (
        EducationAuditFlow,
        EducationEquityFlow,
        EducationGradingFlow,
    )

    print("=" * 60)
    print("SCENARIO: Education Fair Assessment (EU AI Act Art. 13)")
    print("  Pattern: Workflow Isolation | Risk: HIGH")
    print("=" * 60)

    print("\n--- Grading Workflow ---")
    grading_flow = EducationGradingFlow()
    grading_flow.kickoff()

    print("\n--- Equity Reporting Workflow (isolated) ---")
    equity_flow = EducationEquityFlow()
    equity_flow.kickoff()

    print("\n--- Audit: Workflow Isolation Verification ---")
    audit_flow = EducationAuditFlow()
    result = audit_flow.kickoff()

    print("\n" + "=" * 60)
    print("Education scenario complete.")
    print(f"Outputs in: {OUTPUT_DIR}/education_*")
    return result


def run_recommendation():
    """Run the product recommendation scenario (LOW-risk).

    Demonstrates Raw-Forward task chaining: a single crew with 3 tasks
    (profile → search → personalize) where agents consume raw aggregated
    context rather than reading from ``semantic_payload``. No oversight
    or audit crews required for LOW-risk scenarios.
    """
    from agent.flows.recommendation_flow import RecommendationFlow

    print("=" * 60)
    print("SCENARIO: Product Recommendation (LOW-risk)")
    print("  Pattern: Raw-Forward | Risk: LOW")
    print("=" * 60)

    flow = RecommendationFlow()
    result = flow.kickoff()

    print("\n" + "=" * 60)
    print("Recommendation scenario complete.")
    print(f"Outputs in: {OUTPUT_DIR}/recommendation_*")
    return result


def main():
    parser = argparse.ArgumentParser(description="Run jhcontext-aws agent scenarios")
    parser.add_argument(
        "--scenario",
        choices=["healthcare", "education", "recommendation", "all"],
        default="all",
        help="Which scenario to run (default: all)",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.scenario in ("healthcare", "all"):
        run_healthcare()

    if args.scenario in ("education", "all"):
        run_education()

    if args.scenario in ("recommendation", "all"):
        run_recommendation()

    # Print summary
    print("\n" + "=" * 60)
    print("ALL SCENARIOS COMPLETE")
    print("=" * 60)
    output_files = sorted(OUTPUT_DIR.glob("*"))
    for f in output_files:
        size = f.stat().st_size
        print(f"  {f.name:45s} {size:>8,d} bytes")


if __name__ == "__main__":
    main()

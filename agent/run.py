"""Entry point for running jhcontext-crewai agent scenarios.

Usage:
    python -m agent.run --scenario healthcare
    python -m agent.run --scenario education-fair        # fair grading (Art. 13)
    python -m agent.run --scenario education-rubric      # rubric-grounded grading
    python -m agent.run --scenario education-oral        # multimodal oral-feedback variant (supplementary)
    python -m agent.run --scenario recommendation
    python -m agent.run --scenario all
    python -m agent.run --local --scenario healthcare
    python -m agent.run --validate
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

LOCAL_PORT = 8400
LOCAL_URL = f"http://localhost:{LOCAL_PORT}"


def _load_dotenv():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Don't override existing env vars
        if key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# ── Local server lifecycle ───────────────────────────────────────

@contextmanager
def local_server():
    """Start a local jhcontext server (SQLite) and yield when ready.

    Tries ``chalice local`` first (tests actual Chalice routes with SQLite).
    Falls back to the SDK's FastAPI server if Chalice is not installed.
    """
    import httpx

    os.environ["JHCONTEXT_API_URL"] = LOCAL_URL

    # Try chalice local first (tests the actual Chalice API with SQLite)
    api_dir = Path(__file__).parent.parent / "api"
    proc = None
    server_type = None

    try:
        proc = subprocess.Popen(
            ["chalice", "local", "--port", str(LOCAL_PORT), "--no-autoreload"],
            cwd=str(api_dir),
            env={**os.environ, "JHCONTEXT_LOCAL": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        server_type = "Chalice local (SQLite)"
    except FileNotFoundError:
        pass

    if proc is None:
        # Fall back to SDK FastAPI server
        try:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn",
                    "jhcontext.server.app:create_app",
                    "--factory", "--port", str(LOCAL_PORT),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            server_type = "SDK server (SQLite)"
        except FileNotFoundError:
            print("ERROR: Neither 'chalice' nor 'uvicorn' found.")
            print("Install uvicorn: pip install uvicorn>=0.30")
            sys.exit(1)

    print(f"Starting local server ({server_type}) on port {LOCAL_PORT}...")

    # Wait for server readiness
    ready = False
    for _ in range(20):
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            print(f"ERROR: Local server exited unexpectedly.\n{stderr}")
            sys.exit(1)
        try:
            resp = httpx.get(f"{LOCAL_URL}/health", timeout=1.0)
            if resp.status_code == 200:
                ready = True
                break
        except httpx.ConnectError:
            pass
        time.sleep(0.5)

    if not ready:
        proc.terminate()
        proc.wait(timeout=5)
        print("ERROR: Local server failed to start within 10 seconds.")
        sys.exit(1)

    print(f"Local server ready ({server_type}).\n")

    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\nLocal server stopped.")


# ── Scenario runners ─────────────────────────────────────────────

def run_healthcare():
    """Run the healthcare human oversight scenario (Article 14)."""
    import agent.output_dir as _out
    from agent.flows.healthcare_flow import HealthcareFlow

    print("=" * 60)
    print("SCENARIO: Healthcare Human Oversight (EU AI Act Art. 14)")
    print("  Pattern: Semantic-Forward | Risk: HIGH")
    print("=" * 60)

    flow = HealthcareFlow()
    result = flow.kickoff()

    print("\n" + "=" * 60)
    print("Healthcare scenario complete.")
    print(f"Outputs in: {_out.current}/healthcare_*")
    return result


def run_education_fair():
    """Run the education fair assessment scenario (Article 13).

    Uses the 2-agent pipeline focused on Article 13 non-discrimination. For
    the richer three-scenario rubric-grounded variant, see
    ``run_education_rubric``.
    """
    import agent.output_dir as _out
    from agent.flows.education.fair_grading import (
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
    print(f"Outputs in: {_out.current}/education_*")
    return result


def run_recommendation():
    """Run the product recommendation scenario (LOW-risk)."""
    import agent.output_dir as _out
    from agent.flows.recommendation_flow import RecommendationFlow

    print("=" * 60)
    print("SCENARIO: Product Recommendation (LOW-risk)")
    print("  Pattern: Raw-Forward | Risk: LOW")
    print("=" * 60)

    flow = RecommendationFlow()
    result = flow.kickoff()

    print("\n" + "=" * 60)
    print("Recommendation scenario complete.")
    print(f"Outputs in: {_out.current}/recommendation_*")
    return result


def run_education_rubric():
    """Run the rubric-grounded three-scenario education variant.

    Exercises a shared 3-agent pipeline (ingestion → criterion-scoring →
    feedback), an isolated equity workflow, a TA review with temporal
    oversight, and a combined audit that runs four SDK verifiers covering
    Scenarios A, B, and C (EU AI Act Annex III §3).
    """
    import agent.output_dir as _out
    from agent.flows.education.rubric_feedback_grading import (
        RubricAuditFlow,
        RubricEquityFlow,
        RubricGradingFlow,
        RubricTAReviewFlow,
    )

    print("=" * 60)
    print("SCENARIO: Rubric-Grounded Grading (EU AI Act Annex III §3)")
    print("  Pipeline: ingestion → scoring → feedback (+TA review)")
    print("  Scenarios: (A) identity-blind grading, (B) rubric-grounded")
    print("             feedback, (C) human–AI collaborative grading")
    print("  Risk: HIGH")
    print("=" * 60)

    print("\n--- Grading Pipeline (Scenarios A + B) ---")
    RubricGradingFlow().kickoff()

    print("\n--- Equity Reporting Workflow (isolated) ---")
    RubricEquityFlow().kickoff()

    print("\n--- TA Review (Scenario C — temporal oversight) ---")
    RubricTAReviewFlow().kickoff()

    print("\n--- Combined Audit (three verifiers) ---")
    result = RubricAuditFlow().kickoff()

    print("\n" + "=" * 60)
    print("Rubric-grounded grading scenario complete.")
    print(f"Outputs in: {_out.current}/education_rubric_*")
    return result


def run_education_oral():
    """Run the multimodal oral-feedback variant (supplementary).

    Extends the rubric-grounded pattern (Scenarios A/B/C) to audio
    submissions: per-sentence feedback is bound to a (start_ms, end_ms)
    evidence window in the audio, audited via ``verify_multimodal_binding``.
    Demonstrates the same protocol primitives over a non-text modality.
    """
    import agent.output_dir as _out
    from agent.flows.education.oral_feedback_grading import (
        OralAuditFlow,
        OralEquityFlow,
        OralGradingFlow,
        OralTAReviewFlow,
    )

    print("=" * 60)
    print("SCENARIO: Multimodal Oral Feedback (supplementary)")
    print("  Pipeline: audio-ingestion → scoring → feedback (+TA review)")
    print("  Audit:    multimodal_binding + temporal_oversight + workflow_isolation")
    print("  Risk:     HIGH")
    print("=" * 60)

    print("\n--- Audio Grading Pipeline ---")
    OralGradingFlow().kickoff()

    print("\n--- Equity Reporting Workflow (isolated) ---")
    OralEquityFlow().kickoff()

    print("\n--- TA Review (temporal oversight) ---")
    OralTAReviewFlow().kickoff()

    print("\n--- Combined Audit ---")
    result = OralAuditFlow().kickoff()

    print("\n" + "=" * 60)
    print("Oral feedback scenario complete.")
    print(f"Outputs in: {_out.current}/education_oral_*")
    return result


def run_finance():
    """Run the financial credit assessment scenario (Annex III 5b, Articles 13/14)."""
    import agent.output_dir as _out
    from agent.flows.finance_flow import (
        FinanceAuditFlow,
        FinanceCreditFlow,
        FinanceFairLendingFlow,
    )

    print("=" * 60)
    print("SCENARIO: Financial Credit Assessment (EU AI Act Annex III 5b)")
    print("  Pattern: Composite (Negative Proof + Temporal Oversight")
    print("           + Workflow Isolation + PII Detachment)")
    print("  Risk: HIGH")
    print("=" * 60)

    print("\n--- Credit Assessment Pipeline ---")
    credit_flow = FinanceCreditFlow()
    credit_flow.kickoff()

    print("\n--- Fair Lending Reporting (isolated) ---")
    fair_lending_flow = FinanceFairLendingFlow()
    fair_lending_flow.kickoff()

    print("\n--- Audit: Cross-Workflow Verification ---")
    audit_flow = FinanceAuditFlow()
    result = audit_flow.kickoff()

    print("\n" + "=" * 60)
    print("Finance scenario complete.")
    print(f"Outputs in: {_out.current}/finance_*")
    return result


def _run_scenarios(args):
    """Dispatch scenario execution based on parsed args."""
    from agent.output_dir import next_run_dir, set_current

    run_dir = next_run_dir()
    set_current(run_dir)
    print(f"Run directory: {run_dir}\n")

    if args.scenario in ("healthcare", "all"):
        run_healthcare()

    if args.scenario in ("education-fair", "all"):
        run_education_fair()

    if args.scenario in ("education-rubric", "all"):
        run_education_rubric()

    if args.scenario in ("education-oral", "all"):
        run_education_oral()

    if args.scenario in ("recommendation", "all"):
        run_recommendation()

    if args.scenario in ("finance", "all"):
        run_finance()

    # Print summary
    print("\n" + "=" * 60)
    print(f"ALL SCENARIOS COMPLETE — {run_dir.name}")
    print("=" * 60)
    output_files = sorted(run_dir.glob("*"))
    for f in output_files:
        if f.is_file():
            size = f.stat().st_size
            print(f"  {f.name:45s} {size:>8,d} bytes")


# ── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run jhcontext-crewai agent scenarios")
    parser.add_argument(
        "--scenario",
        choices=["healthcare", "education-fair", "education-rubric", "recommendation", "finance", "all"],
        default="all",
        help="Which scenario to run (default: all)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Auto-start a local jhcontext server (SQLite backend)",
    )
    parser.add_argument(
        "--validate",
        nargs="?",
        const="latest",
        default=None,
        metavar="RUN",
        help="Validate a run (default: latest). Use run name e.g. --validate v01",
    )
    args = parser.parse_args()

    if args.validate is not None:
        from agent.output_dir import RUNS_DIR, LATEST_LINK, set_current
        from agent.validate import run_validation

        run_name = args.validate
        if run_name == "latest":
            if LATEST_LINK.exists():
                set_current(LATEST_LINK.resolve())
            elif RUNS_DIR.exists():
                runs = sorted(RUNS_DIR.glob("v[0-9][0-9]"))
                if runs:
                    set_current(runs[-1])
                else:
                    print("ERROR: No runs found. Run scenarios first.")
                    sys.exit(1)
            else:
                print("ERROR: No runs found. Run scenarios first.")
                sys.exit(1)
        else:
            target = RUNS_DIR / run_name
            if not target.exists():
                print(f"ERROR: Run '{run_name}' not found at {target}")
                sys.exit(1)
            set_current(target)

        sys.exit(run_validation())

    if args.local:
        with local_server():
            _run_scenarios(args)
    else:
        _run_scenarios(args)


if __name__ == "__main__":
    main()

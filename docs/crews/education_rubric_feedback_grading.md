# Education Crew (rubric-grounded) — Annex III §3 Three-Scenario Audit

> **Variant mapping.** This document describes the **rubric-grounded
> grading** variant (`agent/flows/education/rubric_feedback_grading.py`,
> `agent/crews/education/rubric_feedback_grading/`). For the lighter
> fairness-only variant (2-agent pipeline + equity isolation) see
> [`education.md`](education.md). For the supplementary multimodal
> variant that extends the same A/B/C pattern to audio submissions
> (per-sentence binding to `(start_ms, end_ms)` audio windows audited
> via `verify_multimodal_binding`), see
> `agent/flows/education/oral_feedback_grading.py` —
> CLI entry: `python -m agent.run --scenario education-oral`.

Compliance scenario set: a shared three-agent AI evaluation pipeline
(ingestion → criterion-scoring → feedback) audited from three angles that
jointly cover EU AI Act Annex III §3 obligations for AI-based learning
outcome assessment. Per-feedback-sentence envelopes, an isolated equity
workflow, and a teaching-assistant review with temporal-oversight
verification.

## Overview

| Property | Value |
|----------|-------|
| Risk Level | **HIGH** (grading + TA review) / MEDIUM (equity) |
| Forwarding Policy | Semantic-Forward |
| Human Oversight | **Required** (Scenario C — verify_temporal_oversight) |
| EU AI Act | Annex III §3 (education high-risk), Art. 12 logging, Art. 14 oversight, Art. 86 meaningful information |
| Crews | 6 (Ingestion, Criterion-Scoring, Feedback, Equity, TA-Review, Audit) |
| Flows | 4 (`Grading`, `Equity`, `TAReview`, `Audit`) |
| Verifiers | 4 (`verify_negative_proof`, `verify_workflow_isolation`, `verify_rubric_grounding`, `verify_temporal_oversight`) |

## The three scenarios

| Scenario | What it proves | Verifier(s) |
|---|---|---|
| **A** — Identity-blind essay grading | Identity attributes (name, ID, accommodation) never enter the grading chain; equity-monitoring workflow is architecturally isolated | `verify_negative_proof` + `verify_workflow_isolation` |
| **B** — Rubric-grounded LLM feedback | Every LLM-generated feedback sentence is case-level bound to a rubric criterion + evidence span in the submission + model version + prompt-template hash | `verify_rubric_grounding` |
| **C** — Human–AI collaborative grading | TA review occurred after AI output, expected documents were opened, grade commit followed review | `verify_temporal_oversight` |

## Architecture

The scenarios share a **three-agent pipeline** (ingestion →
criterion-scoring → feedback) on which the three audits are applied.
Scenario A uses a parallel, isolated equity workflow. Scenario C adds a
TA review step with fine-grained document-access PROV events.

```
┌──────────────────────────────────────────────────────────────────────┐
│                  RubricGradingFlow                                   │
│                                                                      │
│   ingestion_agent ──→ criterion_scoring_agent ──→ feedback_agent     │
│   (Haiku)             (Haiku)                     (Sonnet)           │
│   art-ingestion       art-scoring                 art-feedback       │
│                                                         │            │
│   Identity stripped   Per-criterion scores with   Per-sentence       │
│   at ingestion.       evidence-span hints.        envelopes with     │
│   Grading sees        Consumes ONLY essay +       rubricCriterionId  │
│   ONLY essay text.    rubric.                     + evidenceSpanHash │
│                                                         │            │
│   context_id: ctx-rubric-grading-...                    │            │
└─────────────────────────────────────────────────────────┼────────────┘
                                                          │
          ╳ ZERO SHARED ARTIFACTS ╳                       │
                                                          ▼
┌──────────────────────────────────────────────────────────────────────┐
│                  RubricEquityFlow                                    │
│                                                                      │
│   equity_agent (Haiku)                                               │
│   Aggregate demographic statistics ONLY.                             │
│   context_id: ctx-rubric-equity-...                                  │
└──────────────────────────────────────────────────────────────────────┘

                            ↓ (grading pipeline PROV)

┌──────────────────────────────────────────────────────────────────────┐
│                  RubricTAReviewFlow                                  │
│                                                                      │
│   act-ai-feedback (stub)                                             │
│        ↓                                                             │
│   act-ta-open-submission   ──┐                                       │
│   act-ta-open-rubric         ├─→ act-oversight (ta_review_agent,     │
│   act-ta-open-ai-score       │                 Sonnet)               │
│   act-ta-open-ai-feedback  ──┘                                       │
│        ↓                                                             │
│   act-grade-commit                                                   │
│   context_id: ctx-rubric-ta-review-...                               │
└──────────────────────────────────────────────────────────────────────┘

                            ↓ (all three PROVs + per-sentence index)

┌──────────────────────────────────────────────────────────────────────┐
│                  RubricAuditFlow                                     │
│                                                                      │
│   verify_negative_proof     (Scenario A)                             │
│   verify_workflow_isolation (Scenario A)                             │
│   verify_rubric_grounding   (Scenario B)                             │
│   verify_temporal_oversight (Scenario C)                             │
│         +                                                            │
│   audit_agent (Sonnet)   → narrative compliance report               │
└──────────────────────────────────────────────────────────────────────┘
```

## Agents

| Agent | LLM | Crew | Role |
|---|---|---|---|
| `ingestion_agent` | Haiku | `RubricIngestionCrew` | Strip identity, tokenise, extract rubric-evidence spans |
| `criterion_scoring_agent` | Haiku | `RubricCriterionScoringCrew` | Per-criterion scores (C1..C4) with evidence-span hints |
| `feedback_agent` | Sonnet | `RubricFeedbackCrew` | 6–10 feedback sentences tagged with `rubric_criterion_id` + `evidence_span` |
| `equity_agent` | Haiku | `RubricEquityCrew` | Isolated cohort equity reporting |
| `ta_review_agent` | Sonnet | `RubricTAReviewCrew` | TA review narrative: confirm / modify / override AI output |
| `audit_agent` | Sonnet | `RubricAuditCrew` | Three-scenario narrative report fed by the SDK verifiers |

## PROV structure

The grading flow's PROV graph contains:

- `art-ingestion` — anonymised essay (submission entity)
- `art-scoring` — per-criterion score artifact
- `art-feedback` — aggregate feedback artifact
- `art-feedback-fb-01 … art-feedback-fb-NN` — one entity per LLM-generated
  feedback sentence, each annotated with:
  - `jh:rubricCriterionId` — e.g. `rubric_v2.3#C3-evidence_integration`
  - `jh:evidenceSpanHash` — SHA-256 of cited span
  - `jh:evidenceSpanOffset`, `jh:evidenceSpanLength` — span coordinates
  - `jh:modelVersion`, `jh:promptTemplateHash`
  - `prov:wasDerivedFrom` → `art-ingestion` (submission)
- Per-agent `prov:actedOnBehalfOf crew:rubric-grading` relations

The TA review flow's PROV graph contains four fine-grained document-access
activities (`act-ta-open-*`) plus the umbrella `act-oversight` review
activity and a `act-grade-commit` commit activity.

## Output files

```
output/vNN/
├── education_rubric_envelopes.json              Per-task + per-sentence envelopes
├── education_rubric_prov.ttl                    Grading pipeline PROV (Turtle)
├── education_rubric_equity_prov.ttl             Isolated equity PROV (Turtle)
├── education_rubric_ta_review_prov.ttl          TA review PROV (Turtle)
├── education_rubric_feedback_sentences.json     Per-sentence index for audit
├── education_rubric_metrics.json                Timing metrics
└── education_rubric_audit.json                  Three-scenario audit report
```

## Running

```bash
# Requires ANTHROPIC_API_KEY in .env
cd jhcontext-crewai
source .venv/bin/activate
python -m agent.run --local --scenario education-rubric

# Validate the run afterwards
python -m agent.run --validate
```

## Expected audit output (shape)

```json
{
  "scenario_a": {
    "negative_proof": {"passed": true, "evidence": {...}},
    "workflow_isolation": {"passed": true, "evidence": {...}}
  },
  "scenario_b": {
    "rubric_grounding": {
      "passed": true,
      "evidence": {"grounded_count": 8, "orphan_count": 0, "orphans": []}
    }
  },
  "scenario_c": {
    "temporal_oversight": {
      "passed": true,
      "evidence": {"total_review_seconds": 11, "human_activities_after_ai": ["act-oversight"]}
    }
  },
  "audit_narrative": "…LLM-generated compliance report…",
  "overall_passed": true
}
```

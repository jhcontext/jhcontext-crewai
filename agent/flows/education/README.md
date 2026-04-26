# `agent/flows/education/` — scenario-to-module mapping

Three separate subpackages, one per education pipeline variant. The
modules do not share pipeline code: each mirrors its own architectural
description verbatim so that a reviewer can map flows back to the
scenario descriptions without cross-referencing.

## Scenario ↔ module map

| Scenario | Focus | Module | Class entry points |
|---|---|---|---|
| **A — Identity-Blind Essay Grading** | Article 13 non-discrimination via workflow isolation | `fair_grading.py` | `EducationGradingFlow`, `EducationEquityFlow`, `EducationAuditFlow` |
| **B — Rubric-Grounded LLM Feedback** | Per-sentence Interpretation+Application bindings to rubric criteria with evidence spans | `rubric_feedback_grading.py` | `RubricGradingFlow` (ingestion → criterion-scoring → feedback) |
| **C — Human–AI Collaborative Grading** | Temporal oversight: TA review activity recorded after AI output, before grade commit | `rubric_feedback_grading.py` | `RubricTAReviewFlow` |
| Combined audit (A+B+C) | Runs `verify_negative_proof` + `verify_workflow_isolation` + `verify_rubric_grounding` + `verify_temporal_oversight` | `rubric_feedback_grading.py` | `RubricAuditFlow` |
| Supplementary — multimodal variant | Same A/B/C pattern with audio submissions (per-sentence binding via `(start_ms, end_ms)` audio windows, audited with `verify_multimodal_binding`) | `oral_feedback_grading.py` | `OralGradingFlow`, `OralEquityFlow`, `OralTAReviewFlow`, `OralAuditFlow` |

| Module | Pipeline shape |
|---|---|
| `fair_grading.py` | 2-agent chain: `ingestion → grading`, plus isolated equity workflow and cross-workflow audit |
| `rubric_feedback_grading.py` | 3-agent chain: `ingestion → criterion-scoring → feedback` (per-sentence envelope emission) + equity + TA-review + combined audit |
| `oral_feedback_grading.py` | 3-agent chain: `audio_ingestion (STT+alignment) → criterion-scoring → feedback` + equity + TA-review (with audio-open event) + multimodal audit |

## Crews

The corresponding crews live under the parallel structure
`agent/crews/education/` with the same `fair_grading/` and
`rubric_feedback_grading/` split — `EducationIngestionCrew` etc. under
`fair_grading/crew.py`, `Rubric*Crew` under
`rubric_feedback_grading/crew.py`. Each crew has its own YAML config folder
next to the crew module.

## Why two subpackages instead of one shared pipeline

The fair-grading variant is a two-agent chain; the rubric-grounded variant
is a three-agent chain with an additional feedback step that emits
per-sentence envelopes. Retro-fitting the feedback agent into the
fair-grading chain would make the fair-grading code inconsistent with its
intended minimal scope. Keeping the two in separate subpackages — even with
some duplication at the equity-workflow layer — makes each variant's code
self-contained and reviewable in isolation.

## Entry points

```bash
# Scenario A — fair grading (2-agent pipeline + equity + audit)
python -m agent.run --local --scenario education-fair

# Scenarios A + B + C — rubric-grounded grading (3-agent pipeline + equity + TA review + four-verifier audit)
python -m agent.run --local --scenario education-rubric

# Supplementary — multimodal oral-feedback variant (audio modality)
python -m agent.run --local --scenario education-oral
```

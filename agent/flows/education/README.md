# `agent/flows/education/` — scenario-to-module mapping

Three separate subpackages, one per education pipeline variant. The
modules do not share pipeline code: each mirrors its own architectural
description verbatim so that a reviewer can map flows back to the
scenario descriptions without cross-referencing.

| Module | Focus | Pipeline shape | Scope |
|---|---|---|---|
| `fair_grading.py` | **Fair grading** — Article 13 EU AI Act non-discrimination | 2-agent chain: `ingestion → grading`, plus isolated equity workflow and cross-workflow audit | Identity-blind grading with workflow isolation |
| `rubric_feedback_grading.py` | **Rubric-grounded grading (text)** — auditable AI assessment on essays | 3-agent chain: `ingestion → criterion-scoring → feedback` (per-sentence envelope emission), plus isolated equity workflow, TA-review flow with temporal oversight, and a combined audit that runs three verifiers | Three scenarios — (A) identity-blind grading, (B) rubric-grounded LLM feedback, (C) human–AI collaborative grading |
| `oral_feedback_grading.py` | **Rubric-grounded grading (multimodal)** — auditable AI assessment on audio submissions | 3-agent chain: `audio_ingestion (STT+alignment) → criterion-scoring → feedback` (per-sentence envelope bound to `(start_ms, end_ms)` on the audio), plus isolated equity workflow, TA-review flow that includes an audio-open event, and a combined audit that runs `verify_negative_proof` + `verify_workflow_isolation` + `verify_multimodal_binding` + `verify_temporal_oversight` | Three multimodal scenarios — (A) identity-blind oral grading, (B) rubric-grounded oral feedback with audio-window binding, (C) human–AI collaborative oral grading |

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
# Fair-grading scenario (2-agent pipeline + equity + audit)
python -m agent.run --local --scenario education-fair

# Rubric-grounded scenario (3-agent pipeline + equity + TA review + three-verifier audit)
python -m agent.run --local --scenario education-rubric
```

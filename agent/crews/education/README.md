# `agent/crews/education/` — scenario-to-module mapping

Three subpackages of CrewAI crews, one per education pipeline variant.
See also the parallel split under `agent/flows/education/`.

| Subpackage | Focus | Crews | Agents |
|---|---|---|---|
| `fair_grading/` | **Fair grading** — Article 13 non-discrimination (negative proof + workflow isolation) | `EducationIngestionCrew`, `EducationGradingCrew`, `EducationEquityCrew`, `EducationAuditCrew` | 4 (ingestion, grading, equity, audit) |
| `rubric_feedback_grading/` | **Rubric-grounded grading (text)** — three scenarios (identity-blind grading, rubric-grounded feedback, human-AI grading review) on a shared pipeline | `RubricIngestionCrew`, `RubricCriterionScoringCrew`, `RubricFeedbackCrew`, `RubricEquityCrew`, `RubricTAReviewCrew`, `RubricAuditCrew` | 6 (ingestion, criterion-scoring, feedback, equity, TA review, audit) |
| `oral_feedback_grading/` | **Rubric-grounded grading (multimodal)** — audio-submission variant of the three scenarios; feedback sentences bind to (start_ms, end_ms) windows and the audit uses `verify_multimodal_binding` | `OralAudioIngestionCrew`, `OralCriterionScoringCrew`, `OralFeedbackCrew`, `OralEquityCrew`, `OralTAReviewCrew`, `OralAuditCrew` | 6 (audio ingestion, criterion-scoring, feedback, equity, TA review, audit) |

## YAMLs

Each subpackage ships its own `config/` directory with scenario-specific
`*_agents.yaml` / `*_tasks.yaml` files. Paths are resolved relative to the
crew module (`@CrewBase`'s default behaviour), so moving the crews into a
subpackage does not require editing the YAML paths.

## Duplication policy

The `rubric_feedback_grading` equity crew is a clone of the `fair_grading`
equity crew with a different producer DID. The duplication is deliberate:
keeping each subpackage self-contained lets a reviewer opening one folder
see every crew that variant exercises, without cross-referencing the other.

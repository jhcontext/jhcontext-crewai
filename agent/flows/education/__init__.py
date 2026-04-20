"""Education flows, organised by pipeline variant.

- ``fair_grading`` — 2-agent pipeline for Article 13 non-discrimination.
- ``rubric_feedback_grading`` — 3-agent pipeline with per-sentence
  feedback envelopes plus TA-review and audit flows (covers three
  text-essay scenarios).
- ``oral_feedback_grading`` — multimodal extension of
  ``rubric_feedback_grading``. Input is a student audio submission;
  feedback sentences bind to (start_ms, end_ms) windows; audit uses
  ``verify_multimodal_binding``.

See ``agent/flows/education/README.md`` for the full scenario mapping.
"""

from .fair_grading import (
    EducationAuditFlow,
    EducationEquityFlow,
    EducationGradingFlow,
)
from .rubric_feedback_grading import (
    RubricAuditFlow,
    RubricEquityFlow,
    RubricGradingFlow,
    RubricTAReviewFlow,
)
from .oral_feedback_grading import (
    OralAuditFlow,
    OralEquityFlow,
    OralGradingFlow,
    OralTAReviewFlow,
)

__all__ = [
    # Fair grading (Article 13 non-discrimination)
    "EducationAuditFlow",
    "EducationEquityFlow",
    "EducationGradingFlow",
    # Rubric-grounded grading (three-scenario text pipeline)
    "RubricAuditFlow",
    "RubricEquityFlow",
    "RubricGradingFlow",
    "RubricTAReviewFlow",
    # Oral rubric-grounded grading (three-scenario multimodal pipeline)
    "OralAuditFlow",
    "OralEquityFlow",
    "OralGradingFlow",
    "OralTAReviewFlow",
]

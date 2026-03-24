"""Education domain ontology for UserML semantic payloads.

Predicates correspond to the fair-assessment scenario described in the
AIS 2026 paper (EU AI Act Article 13 — non-discrimination).
"""

from __future__ import annotations

from jhcontext.semantics import (
    interpretation,
    observation,
    situation,
    userml_payload,
)

# ── Valid predicates per UserML layer ────────────────────────────────

EDUCATION_PREDICATES: dict[str, list[str]] = {
    "observation": [
        "rubric_score",
        "word_count",
        "citation_count",
        "structural_element",
    ],
    "interpretation": [
        "argument_quality",
        "evidence_strength",
        "writing_clarity",
        "critical_thinking",
    ],
    "situation": [
        "isInSituation",
        "assessment_complete",
        "grade_assigned",
        "review_pending",
    ],
    "application": [
        "overall_grade",
        "grade_confidence",
        "rubric_weights",
    ],
}


# ── Helper functions ─────────────────────────────────────────────────

def education_observations(essay_id: str, word_count: int, citation_count: int, structural_elements: list | None = None) -> list[dict]:
    """Build observation-layer entries from essay content metrics."""
    obs = [
        observation(essay_id, "word_count", word_count),
        observation(essay_id, "citation_count", citation_count),
    ]
    for elem in (structural_elements or []):
        obs.append(observation(essay_id, "structural_element", elem))
    return obs


def education_interpretations(essay_id: str, scores: dict[str, float]) -> list[dict]:
    """Build interpretation-layer entries from rubric scores.

    *scores* maps predicate names (argument_quality, evidence_strength,
    writing_clarity, critical_thinking) to 0-1 float scores.
    """
    return [
        interpretation(essay_id, predicate, score, confidence=0.9)
        for predicate, score in scores.items()
    ]


def education_situations(essay_id: str, grade: str, confidence: float = 0.9) -> list[dict]:
    """Build situation-layer entries for grading result."""
    return [
        situation(essay_id, "grade_assigned", confidence=confidence),
    ]


def education_payload(essay_id: str, observations: list, interpretations: list | None = None, situations: list | None = None, application: list | None = None) -> dict:
    """Build a complete UserML payload for the education domain."""
    return userml_payload(
        observations=observations,
        interpretations=interpretations or [],
        situations=situations or [],
        application=application or [],
    )


def sample_education(essay_id: str = "essay-S-98765") -> dict:
    """Sample education payload for few-shot examples in task YAML."""
    obs = [
        observation(essay_id, "word_count", 1500),
        observation(essay_id, "citation_count", 12),
        observation(essay_id, "structural_element", "introduction"),
        observation(essay_id, "structural_element", "thesis_statement"),
        observation(essay_id, "structural_element", "conclusion"),
    ]
    interps = [
        interpretation(essay_id, "argument_quality", 0.82, confidence=0.9),
        interpretation(essay_id, "evidence_strength", 0.78, confidence=0.85),
        interpretation(essay_id, "writing_clarity", 0.88, confidence=0.92),
        interpretation(essay_id, "critical_thinking", 0.75, confidence=0.87),
    ]
    sits = [
        situation(essay_id, "grade_assigned", confidence=0.88),
    ]
    app = [
        {"predicate": "overall_grade", "object": {"letter": "B+", "numeric": 87}},
        {"predicate": "grade_confidence", "object": 0.88},
        {"predicate": "rubric_weights", "object": {"argument_quality": 0.3, "evidence_use": 0.3, "writing_clarity": 0.2, "critical_thinking": 0.2}},
    ]
    return userml_payload(observations=obs, interpretations=interps, situations=sits, application=app)

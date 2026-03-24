"""Healthcare domain ontology for UserML semantic payloads.

Predicates are organized per UserML layer and correspond to the clinical
treatment-recommendation scenario described in the AIS 2026 paper
(EU AI Act Article 14 — human oversight).
"""

from __future__ import annotations

from jhcontext.semantics import (
    interpretation,
    observation,
    situation,
    userml_payload,
)

# ── Valid predicates per UserML layer ────────────────────────────────

HEALTHCARE_PREDICATES: dict[str, list[str]] = {
    "observation": [
        "vital_sign",
        "lab_result",
        "imaging_finding",
        "demographic",
        "medication_history",
    ],
    "interpretation": [
        "risk_assessment",
        "clinical_pattern",
        "treatment_response",
        "biomarker_trend",
    ],
    "situation": [
        "isInSituation",
        "treatment_candidate",
        "monitoring_required",
        "acute_episode",
        "stable_remission",
    ],
    "application": [
        "treatment_recommendation",
        "oversight_required",
        "confidence_score",
    ],
}


# ── Helper functions ─────────────────────────────────────────────────

def healthcare_observations(patient_id: str, demographics: dict, labs: list, imaging: list) -> list[dict]:
    """Build observation-layer entries from clinical data."""
    obs = []
    if demographics:
        obs.append(observation(patient_id, "demographic", demographics))
    for lab in labs:
        obs.append(observation(patient_id, "lab_result", lab))
    for img in imaging:
        obs.append(observation(patient_id, "imaging_finding", img))
    return obs


def healthcare_interpretations(patient_id: str, risk_level: str, patterns: list, confidence: float = 0.9) -> list[dict]:
    """Build interpretation-layer entries from clinical analysis."""
    interps = [
        interpretation(patient_id, "risk_assessment", risk_level, confidence=confidence),
    ]
    for p in patterns:
        interps.append(interpretation(patient_id, "clinical_pattern", p, confidence=confidence))
    return interps


def healthcare_situations(patient_id: str, situation_type: str, start: str | None = None, confidence: float = 0.9) -> list[dict]:
    """Build situation-layer entries."""
    return [situation(patient_id, situation_type, start=start, confidence=confidence)]


def healthcare_payload(patient_id: str, observations: list, interpretations: list | None = None, situations: list | None = None, application: list | None = None) -> dict:
    """Build a complete UserML payload for the healthcare domain."""
    return userml_payload(
        observations=observations,
        interpretations=interpretations or [],
        situations=situations or [],
        application=application or [],
    )


def sample_healthcare(patient_id: str = "P-12345", now_iso: str = "2026-03-24T10:00:00Z") -> dict:
    """Sample healthcare payload for few-shot examples in task YAML."""
    obs = [
        observation(patient_id, "demographic", {"age": 62, "gender": "M"}),
        observation(patient_id, "lab_result", {"name": "CEA", "value": 12.5, "unit": "ng/mL"}),
        observation(patient_id, "lab_result", {"name": "WBC", "value": 7.2, "unit": "K/uL"}),
        observation(patient_id, "imaging_finding", "2.3cm pulmonary nodule RUL, decreased from 3.1cm"),
    ]
    interps = [
        interpretation(patient_id, "risk_assessment", "high", confidence=0.87),
        interpretation(patient_id, "clinical_pattern", "responding_to_treatment", confidence=0.82),
        interpretation(patient_id, "biomarker_trend", "elevated_but_decreasing", confidence=0.78),
    ]
    sits = [
        situation(patient_id, "treatment_candidate", start=now_iso, confidence=0.87),
    ]
    app = [
        {"predicate": "treatment_recommendation", "object": "continue_chemotherapy_with_reassessment"},
        {"predicate": "oversight_required", "object": True},
        {"predicate": "confidence_score", "object": 0.87},
    ]
    return userml_payload(observations=obs, interpretations=interps, situations=sits, application=app)

"""Financial domain ontology for UserML semantic payloads.

Predicates correspond to the credit-assessment scenario described in the
AIS 2026 paper (EU AI Act Annex III 5(b) — creditworthiness evaluation,
Articles 13/14 — transparency + human oversight, GDPR Article 22).
"""

from __future__ import annotations

from jhcontext.semantics import (
    interpretation,
    observation,
    situation,
    userml_payload,
)

# ── Valid predicates per UserML layer ────────────────────────────────

FINANCE_PREDICATES: dict[str, list[str]] = {
    "observation": [
        "income_source",
        "employment_record",
        "debt_obligation",
        "payment_history",
        "credit_bureau_score",
        "collateral_value",
    ],
    "interpretation": [
        "debt_to_income_ratio",
        "payment_reliability",
        "employment_stability",
        "credit_utilization",
        "default_probability",
    ],
    "situation": [
        "isInSituation",
        "creditworthy",
        "moderate_risk",
        "high_risk",
        "requires_manual_review",
    ],
    "application": [
        "credit_decision",
        "risk_score",
        "approved_amount",
        "interest_rate",
        "explanation_factors",
    ],
}


# ── Helper functions ─────────────────────────────────────────────────

def finance_observations(applicant_id: str, income: dict, employment: dict, debts: list, payments: dict, bureau_score: int | None = None, collateral: dict | None = None) -> list[dict]:
    """Build observation-layer entries from financial application data."""
    obs = [
        observation(applicant_id, "income_source", income),
        observation(applicant_id, "employment_record", employment),
    ]
    for debt in debts:
        obs.append(observation(applicant_id, "debt_obligation", debt))
    obs.append(observation(applicant_id, "payment_history", payments))
    if bureau_score is not None:
        obs.append(observation(applicant_id, "credit_bureau_score", bureau_score))
    if collateral:
        obs.append(observation(applicant_id, "collateral_value", collateral))
    return obs


def finance_interpretations(applicant_id: str, dti: float, payment_reliability: str, employment_stability: str, default_prob: float, confidence: float = 0.9) -> list[dict]:
    """Build interpretation-layer entries from risk analysis."""
    return [
        interpretation(applicant_id, "debt_to_income_ratio", dti, confidence=confidence),
        interpretation(applicant_id, "payment_reliability", payment_reliability, confidence=confidence),
        interpretation(applicant_id, "employment_stability", employment_stability, confidence=confidence),
        interpretation(applicant_id, "default_probability", default_prob, confidence=confidence),
    ]


def finance_situations(applicant_id: str, situation_type: str, start: str | None = None, confidence: float = 0.9) -> list[dict]:
    """Build situation-layer entries."""
    return [situation(applicant_id, situation_type, start=start, confidence=confidence)]


def finance_payload(applicant_id: str, observations: list, interpretations: list | None = None, situations: list | None = None, application: list | None = None) -> dict:
    """Build a complete UserML payload for the finance domain."""
    return userml_payload(
        observations=observations,
        interpretations=interpretations or [],
        situations=situations or [],
        application=application or [],
    )


def sample_finance(applicant_id: str = "APP-2026-00847", now_iso: str = "2026-03-26T10:00:00Z") -> dict:
    """Sample finance payload for few-shot examples in task YAML."""
    obs = [
        observation(applicant_id, "income_source", {"type": "salary", "monthly_gross": 3800, "currency": "EUR"}),
        observation(applicant_id, "employment_record", {"type": "permanent_contract", "tenure_months": 48, "sector": "engineering"}),
        observation(applicant_id, "debt_obligation", {"type": "auto_loan", "monthly_payment": 280, "remaining_months": 18}),
        observation(applicant_id, "debt_obligation", {"type": "credit_card", "monthly_payment": 140, "credit_limit": 5000}),
        observation(applicant_id, "payment_history", {"on_time_pct": 96, "late_payments_12m": 1, "defaults": 0}),
        observation(applicant_id, "credit_bureau_score", 710),
    ]
    interps = [
        interpretation(applicant_id, "debt_to_income_ratio", 0.32, confidence=0.95),
        interpretation(applicant_id, "payment_reliability", "good", confidence=0.90),
        interpretation(applicant_id, "employment_stability", "stable", confidence=0.92),
        interpretation(applicant_id, "default_probability", 0.04, confidence=0.88),
    ]
    sits = [
        situation(applicant_id, "creditworthy", start=now_iso, confidence=0.88),
    ]
    app = [
        {"predicate": "credit_decision", "object": "conditional_approval"},
        {"predicate": "risk_score", "object": 710},
        {"predicate": "approved_amount", "object": {"value": 25000, "currency": "EUR"}},
        {"predicate": "interest_rate", "object": {"annual_pct": 6.9, "type": "fixed"}},
        {"predicate": "explanation_factors", "object": [
            "Stable employment (48 months permanent contract)",
            "Good payment history (96% on-time)",
            "DTI ratio 32% within acceptable range (<40%)",
            "Credit bureau score 710 (good)",
            "One late payment in 12 months (minor deduction)",
        ]},
    ]
    return userml_payload(observations=obs, interpretations=interps, situations=sits, application=app)

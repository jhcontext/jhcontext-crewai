"""Benefits-domain semantic helper for the A3I crew.

Builds a UserML 4-layer SituationReport (observation → interpretation →
situation → application) for a benefits-eligibility case, using the
jhcontext-sdk semantics builders. Reusable from the Flow when constructing
deterministic envelopes for testing (the LLM-driven crew produces equivalent
output at runtime, but this helper is useful for fixtures + counterfactuals).
"""

from __future__ import annotations

from typing import Any

from jhcontext.semantics import (
    application,
    interpretation,
    observation,
    situation,
)

# Benefits-eligibility rule (worked example for the toeslagenaffaire-style scenario)
TIER_2_THRESHOLD_EUR = 35000


def benefits_eligibility_statement(
    claim_id: str,
    income_eur: int,
    requested_tier: str = "tier_2",
    year: int = 2024,
    source: str | None = "did:gov:case-record-system",
    **_ignored: Any,
) -> dict[str, Any]:
    """Return a UserML SituationReport for one benefits case.

    All four layers are populated. The ``application`` layer carries the
    citizen-facing explanation; the ``situation`` layer carries the
    eligibility verdict; the ``interpretation`` layer carries the
    threshold-comparison and the gap; the ``observation`` layer carries the
    raw recorded income.
    """
    gap = income_eur - TIER_2_THRESHOLD_EUR
    eligible = gap <= 0

    obs = [
        observation(
            subject=claim_id,
            predicate="recorded_income",
            object_={"value": income_eur, "currency": "EUR", "year": year},
            range_="xsd:integer",
            source=source,
        ),
        observation(
            subject=claim_id,
            predicate="claim_tier_requested",
            object_=requested_tier,
            source=source,
        ),
    ]

    interps = [
        interpretation(
            subject=claim_id,
            predicate="tier_eligibility",
            object_="eligible" if eligible else "ineligible_above_threshold",
            confidence=0.99,
            creator="did:gov:a3i-semantic-extractor",
            method="threshold_compare_2024",
        ),
        interpretation(
            subject=claim_id,
            predicate="threshold_gap",
            object_={"value": gap, "currency": "EUR"},
            confidence=0.99,
            creator="did:gov:a3i-semantic-extractor",
            method="arithmetic",
        ),
    ]

    sits = [
        situation(
            subject=claim_id,
            situation_type=(
                "claim_eligible_for_requested_tier"
                if eligible
                else "claim_ineligible_for_requested_tier"
            ),
            confidence=0.99,
        ),
    ]

    explanation_text = (
        f"Your claim is approved for {requested_tier}."
        if eligible
        else (
            f"Your claim was reduced because your recorded income (EUR {income_eur}) "
            f"exceeds the {requested_tier} threshold (EUR {TIER_2_THRESHOLD_EUR}) "
            f"by EUR {gap}."
        )
    )

    apps = [
        application(
            subject=claim_id,
            predicate="citizen_explanation",
            object_=explanation_text,
            auxiliary="hasText",
        ),
        application(
            subject=claim_id,
            predicate="cited_sources",
            object_=[
                "Child Benefit Eligibility Regulation 2024",
                "Income Threshold Guidance §4.2",
                "Benefits Appeals Procedure",
            ],
        ),
        application(
            subject=claim_id,
            predicate="human_oversight_required",
            object_=True,
        ),
    ]

    # Return per-layer lists (the simulate runner consumes them keyed by
    # UserML group). For the SDK's flat SituationReport shape, use
    # jhcontext.semantics.userml_payload(**this_dict_with_pluralised_keys).
    return {
        "observation": obs,
        "interpretation": interps,
        "situation": sits,
        "application": apps,
    }

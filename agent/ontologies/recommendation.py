"""Recommendation domain ontology for UserML semantic payloads.

Predicates correspond to the LOW-risk product-recommendation scenario
demonstrating Raw-Forward policy in the AIS 2026 paper.
"""

from __future__ import annotations

from jhcontext.semantics import (
    interpretation,
    observation,
    situation,
    userml_payload,
)

# ── Valid predicates per UserML layer ────────────────────────────────

RECOMMENDATION_PREDICATES: dict[str, list[str]] = {
    "observation": [
        "browse_event",
        "purchase_event",
        "search_query",
        "price_preference",
    ],
    "interpretation": [
        "category_affinity",
        "brand_preference",
        "price_sensitivity",
        "seasonal_pattern",
    ],
    "situation": [
        "isInSituation",
        "active_shopper",
        "gift_buyer",
        "repeat_customer",
    ],
    "application": [
        "recommended_product",
        "recommendation_confidence",
        "personalization_explanation",
    ],
}


# ── Helper functions ─────────────────────────────────────────────────

def recommendation_observations(user_id: str, browse_events: list, purchases: list, searches: list | None = None) -> list[dict]:
    """Build observation-layer entries from user behavior data."""
    obs = []
    for event in browse_events:
        obs.append(observation(user_id, "browse_event", event))
    for purchase in purchases:
        obs.append(observation(user_id, "purchase_event", purchase))
    for query in (searches or []):
        obs.append(observation(user_id, "search_query", query))
    return obs


def recommendation_interpretations(user_id: str, affinities: dict[str, float], brand_prefs: list | None = None, price_sensitivity: str | None = None) -> list[dict]:
    """Build interpretation-layer entries from preference analysis."""
    interps = []
    for category, score in affinities.items():
        interps.append(interpretation(user_id, "category_affinity", {"category": category, "score": score}, confidence=score))
    for brand in (brand_prefs or []):
        interps.append(interpretation(user_id, "brand_preference", brand, confidence=0.8))
    if price_sensitivity:
        interps.append(interpretation(user_id, "price_sensitivity", price_sensitivity, confidence=0.85))
    return interps


def recommendation_situations(user_id: str, situation_type: str, confidence: float = 0.8) -> list[dict]:
    """Build situation-layer entries."""
    return [situation(user_id, situation_type, confidence=confidence)]


def recommendation_payload(user_id: str, observations: list, interpretations: list | None = None, situations: list | None = None, application: list | None = None) -> dict:
    """Build a complete UserML payload for the recommendation domain."""
    return userml_payload(
        observations=observations,
        interpretations=interpretations or [],
        situations=situations or [],
        application=application or [],
    )


def sample_recommendation(user_id: str = "user-U-54321") -> dict:
    """Sample recommendation payload for few-shot examples in task YAML."""
    obs = [
        observation(user_id, "browse_event", {"category": "electronics", "item": "wireless headphones", "timestamp": "2026-03-23T14:30:00Z"}),
        observation(user_id, "browse_event", {"category": "electronics", "item": "bluetooth speaker", "timestamp": "2026-03-23T15:10:00Z"}),
        observation(user_id, "purchase_event", {"category": "electronics", "item": "USB-C cable", "price": 12.99}),
        observation(user_id, "price_preference", {"min": 20, "max": 150, "currency": "USD"}),
    ]
    interps = [
        interpretation(user_id, "category_affinity", {"category": "electronics", "score": 0.92}, confidence=0.92),
        interpretation(user_id, "brand_preference", "Sony", confidence=0.75),
        interpretation(user_id, "price_sensitivity", "medium", confidence=0.85),
    ]
    sits = [
        situation(user_id, "active_shopper", confidence=0.88),
    ]
    app = [
        {"predicate": "recommended_product", "object": {"name": "Sony WH-1000XM5", "price": 129.99, "confidence": 0.91}},
        {"predicate": "personalization_explanation", "object": "Matches electronics affinity and price range"},
    ]
    return userml_payload(observations=obs, interpretations=interps, situations=sits, application=app)

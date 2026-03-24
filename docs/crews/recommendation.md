# Recommendation Crew — LOW-Risk Product Recommendations

Low-risk product recommendation scenario demonstrating Raw-Forward policy: agents
consume full aggregated context without semantic filtering. The protocol still captures
full provenance and envelopes for traceability, but without the overhead of
Semantic-Forward constraints.

## Overview

| Property | Value |
|----------|-------|
| Risk Level | **LOW** |
| Forwarding Policy | Raw-Forward |
| Human Oversight | Not required |
| Crews | 1 (RecommendationCrew) |
| Total Agents | 3 |
| Total Tasks | 3 |

## Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                  RecommendationCrew                          │
│                                                             │
│   profile_agent ──→ search_agent ──→ personalize_agent      │
│   (Haiku)           (Haiku)          (Sonnet)               │
│   art-profile       art-search       art-personalize        │
│                                                             │
│   Raw-Forward: each agent consumes the full aggregated      │
│   context (CrewAI default). No semantic boundary.           │
└─────────────────────────────────────────────────────────────┘
```

All three tasks run in a single crew with sequential process. Unlike the healthcare
scenario, there is no oversight or audit crew — LOW-risk systems don't require them.

## Agents

### Profile Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (data extraction) |
| DID | `did:ecommerce:profile-agent` |
| Artifact | `art-profile` (SEMANTIC_EXTRACTION) |

**Role:** User Profile Analyst — extracts preferences from browsing and purchase history
for product recommendations.

**Goal:** Analyze user interaction data and produce a structured preference profile
including categories, price range, brand affinities, and recent interests.

**Backstory:** Behavioral analytics specialist with expertise in user segmentation and
preference extraction from interaction patterns. Identifies meaningful signals in noisy
data.

### Search Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (classification) |
| DID | `did:ecommerce:search-agent` |
| Artifact | `art-search` (SEMANTIC_EXTRACTION) |

**Role:** Product Search Agent — matches user preferences to catalog items and ranks
candidates by relevance.

**Goal:** Search the product catalog for items matching the user's preference profile.
Return ranked candidates with relevance scores and match explanations.

**Backstory:** Information retrieval specialist with deep knowledge of product taxonomy
and similarity matching. Surfaces the most relevant items from large catalogs efficiently.

### Personalize Agent

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:ecommerce:personalize-agent` |
| Artifact | `art-personalize` (SEMANTIC_EXTRACTION) |

**Role:** Personalization Agent — generates tailored product recommendations with
explanations.

**Goal:** Select the top 3 products from the candidate list and generate personalized
recommendation explanations that connect each product to the user's specific preferences.

**Backstory:** Customer experience specialist who crafts compelling, honest product
recommendations. Explains why each item fits the user, building trust through
transparency.

## Tasks

### 1. Profile Task

**Agent:** profile_agent
**Input:** User ID, browsing history, purchase history
**Output:** jhcontext Envelope with UserML observation + interpretation layers

Extracts user preferences from interaction data. Uses observation predicates:
`browse_event`, `purchase_event`, `search_query`, `price_preference`. Interpretation
predicates: `category_affinity`, `brand_preference`, `price_sensitivity`,
`seasonal_pattern`.

### 2. Search Task

**Agent:** search_agent
**Context:** Full aggregated context from profile_task (Raw-Forward)
**Output:** Envelope with ranked product candidates

Searches the product catalog and returns top 10 candidates with relevance scores. Uses
interpretation predicates for product-to-preference matching and situation predicates:
`active_shopper`, `gift_buyer`, `repeat_customer`.

### 3. Personalize Task

**Agent:** personalize_agent
**Context:** Full aggregated context from profile + search (Raw-Forward)
**Output:** Envelope with 3 final recommendations in application layer

Generates personalized explanations connecting each product to user preferences. Uses
application predicates: `recommended_product`, `recommendation_confidence`,
`personalization_explanation`.

Includes `decision_influence` metadata with categories: `user_preferences`,
`product_relevance`, `price_fit`.

## Raw-Forward vs Semantic-Forward

In this scenario, all tasks use `forwarding_policy=raw_forward`:

```
profile_task output → search_agent sees EVERYTHING (full envelope + all context)
search_task output  → personalize_agent sees EVERYTHING
```

Contrast with healthcare (Semantic-Forward):
```
sensor_task output  → situation_agent sees only semantic_payload
situation_task output → decision_agent sees only semantic_payload
```

Raw-Forward is permitted for LOW-risk scenarios because:
- No regulatory requirement for data minimization between agents
- Full context improves recommendation quality
- Audit trail still captures everything via PROV graph
- Monotonic enforcement prevents downgrading from Semantic-Forward if a HIGH-risk task
  existed upstream

## PROV Graph Structure

Simple linear chain:

```
Agents:
  did:ecommerce:profile-agent     (role: profile)
  did:ecommerce:search-agent      (role: search)
  did:ecommerce:personalize-agent (role: personalize)

Activities + Entities:
  act-profile ────────→ art-profile (SEMANTIC_EXTRACTION)

  act-search ─────────→ art-search (SEMANTIC_EXTRACTION)
      └─ used: art-profile

  act-personalize ────→ art-personalize (SEMANTIC_EXTRACTION)
      └─ used: art-search
          └─ wasDerivedFrom: art-profile
```

## Output Files

| File | Description |
|------|-------------|
| `recommendation_envelope.json` | Envelope with 3 artifacts, `risk_level=low`, `forwarding_policy=raw_forward` |
| `recommendation_prov.ttl` | PROV graph — 3 agents, 3 activities, 3 entities |
| `recommendation_output.json` | Final recommendations with UserML semantic payload |
| `recommendation_metrics.json` | Per-step timing |

## Running

```bash
python -m agent.run --local --scenario recommendation
```

## Default User

User U-98765:
- Browsing: running shoes, wireless headphones, yoga mats, protein powder, fitness trackers
- Purchases: Nike Air Zoom Pegasus 40 ($120), Bose QuietComfort 45 ($280), Manduka PRO
  yoga mat ($120), Garmin Venu 3 ($450)

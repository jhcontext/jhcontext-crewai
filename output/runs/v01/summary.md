# PAC-AI Validation Run — v01

**Date:** 2026-03-24 18:06 UTC
**Overall:** FAIL

## Artifact Characteristics

| Metric | Healthcare | Education | Recommendation |
|--------|-----------|-----------|----------------|
| Envelope size (bytes) | 3682 | 1809 | 2982 |
| PROV graph size (bytes) | 5608 | 1543 | 2251 |
| Entity count | 9 | 2 | 3 |
| Activity count | 9 | 2 | 3 |
| Agent count | 5 | 2 | 3 |
| Artifact count | 5 | — | 3 |

## Audit Checks

| Check | Healthcare | Education | Recommendation | What it verifies |
|-------|-----------|-----------|----------------|-----------------|
| temporal_oversight | PASS | n/a | n/a | Physician reviewed source docs AFTER AI recommendation (Art. 14) |
| integrity | **FAIL** | n/a | n/a | Envelope hash + signature match (tamper-evidence) |
| workflow_isolation | n/a | PASS | n/a | Zero shared artifacts between grading and equity workflows (Art. 13) |
| negative_proof | n/a | PASS | n/a | Identity data absent from grading PROV chain (Art. 13) |
| semantic_conformance | **FAIL** | **FAIL** | **FAIL** | Semantic payload uses valid UserML predicates from domain ontology |
| risk_level | PASS | n/a | PASS | Envelope risk_level matches expected (high/low) |
| forwarding_policy | PASS | n/a | PASS | Envelope forwarding_policy matches expected (semantic/raw) |

## How to Read Results

- **PASS** — the check succeeded against the protocol specification
- **FAIL** — the check found a violation (see `validation_report.json` for details)
- **n/a** — the check does not apply to this scenario

### Key checks by scenario

**Healthcare (Article 14 — Human Oversight):**
- `temporal_oversight`: Verifies the physician accessed 4 source documents
  (CT scan, treatment history, pathology, AI recommendation) AFTER the AI
  generated its recommendation, with meaningful review duration (not rubber-stamping).
- `integrity`: Verifies the envelope's cryptographic hash and signature are valid.

**Education (Article 13 — Non-Discrimination):**
- `workflow_isolation`: Verifies grading and equity workflows share zero PROV
  entities — complete data isolation between identity and assessment.
- `negative_proof`: Verifies no identity/demographic artifacts appear anywhere
  in the grading dependency chain (recursive traversal).

**Recommendation (LOW-risk):**
- `risk_level=low` + `forwarding_policy=raw_forward`: Confirms LOW-risk
  scenarios correctly use Raw-Forward (no Semantic-Forward constraint needed).

### Semantic conformance

This check verifies LLM agents produced semantic payloads in UserML format
(`{"@model": "UserML", "layers": {...}}`) with valid domain predicates.
Failures here mean the LLM output free-form JSON instead of the structured
UserML format — the protocol still functions, but payloads are not formally
typed. Use `FlatEnvelope` with `output_pydantic` to enforce stricter structure.

## Files in This Run

- `education_audit.json` (19,914 bytes)
- `education_equity_prov.ttl` (817 bytes)
- `education_grading_envelope.json` (1,809 bytes)
- `education_grading_metrics.json` (694 bytes)
- `education_grading_prov.ttl` (1,543 bytes)
- `healthcare_audit.json` (16,758 bytes)
- `healthcare_envelope.json` (3,682 bytes)
- `healthcare_metrics.json` (1,532 bytes)
- `healthcare_prov.ttl` (5,608 bytes)
- `recommendation_envelope.json` (2,982 bytes)
- `recommendation_metrics.json` (970 bytes)
- `recommendation_output.json` (4,693 bytes)
- `recommendation_prov.ttl` (2,251 bytes)
- `validation_report.json` (7,678 bytes)

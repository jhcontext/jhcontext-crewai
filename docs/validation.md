# Protocol Validation

After running scenarios, use `--validate` to produce a structured validation report
matching the paper's tables.

## Running Scenarios + Validation

Each run is saved to a versioned directory (`output/runs/v01/`, `v02/`, etc.):

```bash
# Run all scenarios (creates output/runs/v01/)
python -m agent.run --local --scenario all

# Validate the latest run
python -m agent.run --validate

# Validate a specific run
python -m agent.run --validate v01
```

## Run Directory Structure

```
output/
├── runs/
│   ├── v01/                              ← first run
│   │   ├── healthcare_envelope.json
│   │   ├── healthcare_prov.ttl
│   │   ├── healthcare_audit.json
│   │   ├── healthcare_metrics.json
│   │   ├── education_grading_envelope.json
│   │   ├── education_grading_prov.ttl
│   │   ├── education_equity_prov.ttl
│   │   ├── education_audit.json
│   │   ├── recommendation_envelope.json
│   │   ├── recommendation_prov.ttl
│   │   ├── validation_report.json        ← full machine-readable report
│   │   └── summary.md                    ← human-readable interpretation
│   └── v02/
│       └── ...
└── latest → runs/vNN/                    ← symlink to most recent run
```

Runs are **committed to git** so results are versioned alongside the code.

## Audit Checks

| Check | Article | Scenario | What it proves |
|-------|---------|----------|---------------|
| `temporal_oversight` | Art. 14 | Healthcare | Physician accessed 4 source documents AFTER AI recommendation, with meaningful review duration |
| `integrity` | Art. 15 | All | Envelope hash + signature are valid (tamper-evidence) |
| `workflow_isolation` | Art. 13 | Education | Zero shared PROV entities between grading and equity workflows |
| `negative_proof` | Art. 13 | Education | No identity/demographic artifacts in the grading dependency chain |
| `semantic_conformance` | — | All | Semantic payload uses valid UserML predicates from domain ontology |
| `risk_level` | Art. 9 | All | Envelope risk tier matches expected value |
| `forwarding_policy` | — | All | Forwarding policy matches expected pattern (semantic/raw) |

Result values:
- **PASS** — check succeeded against the protocol specification
- **FAIL** — violation found (details in `validation_report.json`)
- **n/a** — check does not apply to this scenario

## Semantic Payload Conformance

This check verifies LLM agents produced payloads in UserML format with valid domain
predicates from `agent/ontologies/`. Failures mean the LLM wrote free-form JSON instead
of structured UserML — the protocol still functions, but payloads are not formally typed.
Use `FlatEnvelope` with `output_pydantic` to enforce stricter structure (see jhcontext-sdk
README).

## UserML Semantic Payloads

Each scenario structures its `semantic_payload` using the UserML format — a layered
ontology defined in the jhcontext SDK (`jhcontext.semantics`). Domain-specific predicates
are defined in `agent/ontologies/`.

### UserML Structure

```json
{
  "@model": "UserML",
  "layers": {
    "observation": [{"subject": "...", "predicate": "...", "object": ...}],
    "interpretation": [{"subject": "...", "predicate": "...", "object": ..., "confidence": 0.9}],
    "situation": [{"subject": "...", "predicate": "isInSituation", "object": "...", "confidence": 0.9}],
    "application": [{"predicate": "...", "object": ...}]
  }
}
```

### Domain Predicates

| Layer | Healthcare | Education | Recommendation |
|-------|-----------|-----------|----------------|
| **Observation** | vital_sign, lab_result, imaging_finding, demographic, medication_history | rubric_score, word_count, citation_count, structural_element | browse_event, purchase_event, search_query, price_preference |
| **Interpretation** | risk_assessment, clinical_pattern, treatment_response, biomarker_trend | argument_quality, evidence_strength, writing_clarity, critical_thinking | category_affinity, brand_preference, price_sensitivity, seasonal_pattern |
| **Situation** | treatment_candidate, monitoring_required, acute_episode, stable_remission | assessment_complete, grade_assigned, review_pending | active_shopper, gift_buyer, repeat_customer |
| **Application** | treatment_recommendation, oversight_required, confidence_score | overall_grade, grade_confidence, rubric_weights | recommended_product, recommendation_confidence, personalization_explanation |

## PROV Graph Validation

Each scenario produces a W3C PROV graph (Turtle format) that captures the causal history
of every artifact: which agents performed which activities, using which inputs, to produce
which outputs.

### SDK Audit Functions

| Function | Article | Scenario | Verifies |
|----------|---------|----------|----------|
| `verify_temporal_oversight()` | Art. 14 | Healthcare | Physician reviewed source docs (not just AI summary) |
| `verify_negative_proof()` | Art. 13 | Education | Identity data absent from grading chain |
| `verify_workflow_isolation()` | Art. 13 | Education | Zero shared artifacts between workflows |
| `verify_integrity()` | Art. 15 | All | Envelope hash + signature valid |
| `verify_pii_detachment()` | GDPR | Optional | No PII remains in stored payload |

## Metrics for the Paper

The agent collects timing metrics automatically via `ContextMixin._finalize_metrics()`:

| Metric | Source | File |
|--------|--------|------|
| Per-step persist latency (ms) | `_persist_step()` timing | `*_metrics.json` |
| Total flow execution time (ms) | `_init_context()` → `_finalize_metrics()` | `*_metrics.json` |
| Envelope size (bytes) | `output/*.json` file size | Measured post-run |
| PROV graph size (bytes) | `output/*.ttl` file size | Measured post-run |
| Artifact count per envelope | `len(envelope.artifacts_registry)` | From envelope JSON |
| DynamoDB vs SQLite latency | Compare with jhcontext-sdk local benchmarks | Side-by-side |
| Lambda cold start overhead | CloudWatch Logs `INIT_START` duration | AWS console |

## Agent ↔ API Communication Best Practices

### Envelope-per-flow, not envelope-per-task

Each CrewAI Flow creates one envelope with one `context_id`. All tasks within the flow
add artifacts to the same envelope.

### `passed_artifact_pointer` for inter-agent handoff

The `passed_artifact_pointer` field always points to the latest artifact. When Agent B
starts, it reads the envelope and knows which artifact to consume.

### Large artifacts go to S3

The envelope stays small (~5 KB). If a task output exceeds 100 KB, the
`ContextMixin._persist_step()` automatically uploads to S3 via `POST /artifacts`.

### Sign before persist

The `ContextMixin` signs the envelope with the agent's DID before submitting. Each
re-submission re-signs with the latest agent ID. The `proof.content_hash` allows
downstream verification.

### Compliance package as the deliverable

After a flow completes, the canonical output is the compliance package
(`GET /compliance/package/{context_id}`). This is what goes to regulatory auditors,
institutional compliance databases, and the paper's evidence section.

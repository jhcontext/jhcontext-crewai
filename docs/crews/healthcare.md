# Healthcare Crew — Article 14 Human Oversight

EU AI Act Article 14 compliance scenario: a high-risk clinical decision support system
where a physician must meaningfully review AI recommendations before any treatment
decision is finalized.

## Overview

| Property | Value |
|----------|-------|
| Risk Level | **HIGH** |
| Forwarding Policy | Semantic-Forward |
| Human Oversight | Required (physician review with temporal proof) |
| EU AI Act Article | Article 14 — Human Oversight |
| Crews | 3 (Clinical, Oversight, Audit) |
| Total Agents | 5 |
| Total Tasks | 5 |

## Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                  HealthcareClinicalCrew                      │
│                                                             │
│   sensor_agent ──→ situation_agent ──→ decision_agent       │
│   (Haiku)          (Haiku)             (Sonnet)             │
│   art-sensor       art-situation       art-decision         │
│                                                             │
│   Semantic-Forward: each task reads only semantic_payload   │
│   from the previous envelope                                │
└─────────────────────────┬───────────────────────────────────┘
                          │ AI recommendation
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                HealthcareOversightCrew                       │
│                                                             │
│   oversight_agent (Sonnet) — simulates Dr. Chen             │
│                                                             │
│   Code-controlled document access with real timestamps:     │
│     ├─ Access CT scan ──────────── 4 sec review             │
│     ├─ Access treatment history ── 3 sec review             │
│     ├─ Access pathology report ─── 2 sec review             │
│     └─ Review AI recommendation ── 1 sec review             │
│                                                             │
│   → art-oversight                                           │
└─────────────────────────┬───────────────────────────────────┘
                          │ oversight report
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  HealthcareAuditCrew                         │
│                                                             │
│   audit_agent (Sonnet) — compliance verification            │
│                                                             │
│   Programmatic (SDK):                                       │
│     • verify_temporal_oversight() — Art. 14 check           │
│     • verify_integrity() — envelope signature               │
│                                                             │
│   Narrative (LLM):                                          │
│     • Full Article 14 compliance audit report               │
│                                                             │
│   → art-audit                                               │
└─────────────────────────────────────────────────────────────┘
```

## Agents

### Sensor Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (data extraction) |
| DID | `did:hospital:sensor-agent` |
| Artifact | `art-sensor` (TOKEN_SEQUENCE) |

**Role:** Clinical Context Sensor Agent — collects patient data from simulated clinical
sources (EHR, imaging, lab results).

**Goal:** Produce raw observation artifacts (patient demographics, lab results, imaging
metadata) and register them in a jhcontext envelope with content hashes.

**Backstory:** IoT integration specialist for hospital information systems. Extracts
structured data from clinical systems and formats it as standardized observations.

### Situation Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (classification) |
| DID | `did:hospital:situation-agent` |
| Artifact | `art-situation` (SEMANTIC_EXTRACTION) |

**Role:** Clinical Situation Recognition Agent — interprets raw observations into
semantic patient context.

**Goal:** Consume sensor artifacts, produce a semantic extraction (patient situation
summary with risk indicators), and update the envelope.

**Backstory:** Clinical decision support specialist with expertise in patient risk
stratification and pattern recognition across multi-modal clinical data.

### Decision Agent

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:hospital:decision-agent` |
| Artifact | `art-decision` (SEMANTIC_EXTRACTION) |

**Role:** Treatment Recommendation Agent — generates AI-assisted treatment
recommendations based on semantic patient context.

**Goal:** Consume the semantic extraction, generate a treatment recommendation with
confidence score and justification. Set `human_oversight_required=true` for high-risk tier.

**Backstory:** Oncology decision support system with 95% accuracy on standard treatment
protocols. Always flags cases requiring human review.

### Oversight Agent (Dr. Chen)

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:hospital:dr-chen` |
| Artifact | `art-oversight` (SEMANTIC_EXTRACTION) |

**Role:** Physician Review Simulation Agent — simulates meaningful human oversight by
accessing source documents with timestamps.

**Goal:** Access original patient records with timed delays simulating real clinical
review, then approve or override the AI recommendation.

**Backstory:** Simulates Dr. Chen reviewing AI recommendations with genuine clinical
judgment. Takes time to review each document before making a decision.

### Audit Agent

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:hospital:audit-agent` |
| Artifact | `art-audit` (TOOL_RESULT) |

**Role:** Compliance Audit Agent — reconstructs the decision chain from envelopes and
PROV graphs.

**Goal:** Retrieve the envelope, traverse the PROV graph, verify temporal sequencing of
human oversight, and produce an audit report proving Article 14 compliance.

**Backstory:** Healthcare regulatory compliance auditor specializing in EU AI Act
high-risk system verification. Verifies that human oversight was meaningful, not
rubber-stamped.

## Tasks

### 1. Sensor Task

**Agent:** sensor_agent
**Input:** Patient demographics (age, gender), lab results, imaging metadata
**Output:** jhcontext Envelope with `semantic_payload` in UserML format (observation layer)

Collects simulated clinical observations and structures them using healthcare ontology
predicates: `vital_sign`, `lab_result`, `imaging_finding`, `demographic`,
`medication_history`.

Sets `forwarding_policy=raw_forward` — raw data flows freely at the ingestion stage.

### 2. Situation Task

**Agent:** situation_agent
**Context:** sensor_task output
**Output:** Envelope with UserML interpretation + situation layers

Reads `semantic_payload` from the sensor envelope (Semantic-Forward). Produces a clinical
situation classification with risk indicators and assessment priority.

Uses predicates: `risk_assessment`, `clinical_pattern`, `treatment_response`,
`biomarker_trend` (interpretation); `treatment_candidate`, `monitoring_required`,
`acute_episode`, `stable_remission` (situation).

Sets `forwarding_policy=semantic_forward` — this is the **semantic boundary**. From here
on, only structured semantic data flows downstream.

### 3. Decision Task

**Agent:** decision_agent
**Context:** situation_task output
**Output:** Envelope with UserML application layer (treatment recommendation)

Reads semantic extraction from situation task. Generates a treatment recommendation with
confidence score, supporting evidence, and risk assessment.

Uses predicates: `treatment_recommendation`, `oversight_required`, `confidence_score`.

### 4. Oversight Task

**Agent:** oversight_agent
**Input:** AI recommendation from decision task
**Output:** JSON with decision (approve/override), justification, alternatives, notes

The flow code controls document access timing — each source document (CT scan, treatment
history, pathology report, AI recommendation) is accessed with real timestamps. These
become fine-grained PROV activities that prove the physician reviewed documents *after*
the AI produced its recommendation.

### 5. Audit Task

**Agent:** audit_agent
**Input:** Oversight report + context_id
**Output:** Structured compliance audit report

Reconstructs the full decision chain and verifies:
- (a) Physician accessed source documents BEFORE approving/overriding
- (b) Total review duration was meaningful (>5 seconds simulated, >300 seconds production)
- (c) Physician exercised independent judgment (not rubber-stamp)

## PROV Graph Structure

```
Agents:
  did:hospital:sensor-agent     (role: sensor)
  did:hospital:situation-agent  (role: situation)
  did:hospital:decision-agent   (role: decision)
  did:hospital:dr-chen          (role: physician_oversight)
  did:hospital:audit-agent      (role: audit)

Activities + Entities:
  act-sensor ──────────── → art-sensor (TOKEN_SEQUENCE)
  act-situation ──────── → art-situation (SEMANTIC_EXTRACTION)
      └─ used: art-sensor
  act-decision ─────────→ art-decision (SEMANTIC_EXTRACTION)
      └─ used: art-situation

  act-access-ct-scan ───── (4s, dr-chen, used: ent-ct-scan)
  act-access-history ───── (3s, dr-chen, used: ent-treatment-history)
  act-access-pathology ─── (2s, dr-chen, used: ent-pathology)
  act-review-ai ────────── (1s, dr-chen, used: ent-ai-recommendation)

  act-oversight ─────────→ art-oversight (SEMANTIC_EXTRACTION)
      └─ used: art-decision, ent-ct-scan, ent-pathology,
               ent-treatment-history, ent-ai-recommendation

  act-audit ─────────────→ art-audit (TOOL_RESULT)
      └─ used: art-sensor, art-situation, art-decision, art-oversight
```

## Audit Checks

| Check | Article | What it proves |
|-------|---------|---------------|
| `temporal_oversight` | Art. 14 | All 4 physician review activities occur AFTER `act-decision`, with total review time > minimum threshold |
| `integrity` | Art. 15 | Envelope `content_hash` + Ed25519 `signature` are valid (tamper-evidence) |

## Output Files

| File | Description |
|------|-------------|
| `healthcare_envelope.json` | Complete JSON-LD envelope with 5 artifacts, compliance block, proof |
| `healthcare_prov.ttl` | W3C PROV graph (Turtle RDF) — 5 agents, 9 activities, 9 entities |
| `healthcare_audit.json` | Programmatic checks + LLM narrative audit report |
| `healthcare_metrics.json` | Per-step timing (agent, artifact_id, content_size, persist_ms) |

## Running

```bash
python -m agent.run --local --scenario healthcare
```

## Default Patient

Patient P-12345: age 62, male, elevated tumor markers (CEA 12.5 ng/mL), 2.3cm pulmonary
nodule in RUL (decreased from 3.1cm), WBC 7.2 K/uL.

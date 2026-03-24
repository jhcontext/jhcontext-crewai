# Education Crew — Article 13 Non-Discrimination

EU AI Act Article 13 compliance scenario: an AI grading system that must prove identity
data never influenced the grading decision, using workflow isolation and negative
provenance proof.

## Overview

| Property | Value |
|----------|-------|
| Risk Level | **HIGH** (grading) / MEDIUM (equity) |
| Forwarding Policy | Semantic-Forward |
| Human Oversight | Not required (structural isolation instead) |
| EU AI Act Article | Article 13 — Non-Discrimination |
| Crews | 4 (Ingestion, Grading, Equity, Audit) |
| Total Agents | 4 |
| Flows | 3 independent flows (Grading, Equity, Audit) |

## Architecture

The key design principle is **workflow isolation** — grading and equity reporting run as
completely separate flows with separate `context_id`s, separate PROV graphs, and zero
shared artifacts.

```
┌─────────────────────────────────────────────┐
│           EducationGradingFlow              │
│                                             │
│   ingestion_agent ──→ grading_agent         │
│   (Haiku)              (Haiku)              │
│   art-ingestion        art-grading          │
│                                             │
│   Identity stripped at ingestion.           │
│   Grading sees ONLY essay text.             │
│   context_id: ctx-grading-...               │
└─────────────────────────────────────────────┘

          ╳ ZERO SHARED ARTIFACTS ╳

┌─────────────────────────────────────────────┐
│           EducationEquityFlow               │
│                                             │
│   equity_agent (Haiku)                      │
│   art-equity                                │
│                                             │
│   Consumes ONLY aggregate demographics.     │
│   No individual grades. No essay text.      │
│   context_id: ctx-equity-...                │
└─────────────────────────────────────────────┘

                    │
                    ▼ both PROV graphs
┌─────────────────────────────────────────────┐
│           EducationAuditFlow                │
│                                             │
│   audit_agent (Sonnet)                      │
│                                             │
│   Programmatic (SDK):                       │
│     • verify_workflow_isolation()            │
│     • verify_negative_proof()               │
│                                             │
│   Narrative (LLM):                          │
│     • Article 13 compliance audit           │
└─────────────────────────────────────────────┘
```

## Agents

### Ingestion Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (data extraction) |
| DID | `did:university:ingestion-agent` |
| Artifact | `art-ingestion` (TOKEN_SEQUENCE) |

**Role:** Essay Ingestion Agent — receives student essay submissions and strips identity
information before grading.

**Goal:** Separate identity metadata (student name, ID, demographic attributes) from
essay text content. Create envelope with essay text as primary artifact; identity data
stored separately.

**Backstory:** Academic submissions processing system ensuring blind grading. Enforces
strict separation between identity and content to prevent bias in automated assessment.

### Grading Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (classification) |
| DID | `did:university:grading-agent` |
| Artifact | `art-grading` (SEMANTIC_EXTRACTION) |

**Role:** AI Essay Grading Agent — evaluates essay content against rubric criteria
without access to student identity.

**Goal:** Consume ONLY the essay text artifact and rubric criteria. Produce a grade with
confidence score and justification. The `artifacts_registry` must show NO identity
artifacts in the used chain.

**Backstory:** NLP-based assessment system trained on anonymized essay corpora with
rubric-aligned evaluation criteria. Never requests or uses student identity information.

### Equity Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (data extraction) |
| DID | `did:university:equity-agent` |
| Artifact | `art-equity` (SEMANTIC_EXTRACTION) |

**Role:** Equity Reporting Agent — produces aggregate demographic statistics for
institutional compliance (separate workflow).

**Goal:** Consume identity metadata in an ISOLATED workflow with no connection to grading.
Produce aggregate statistics for equity reporting.

**Backstory:** Institutional equity and inclusion reporting system. Operates in a
completely separate data pipeline from the grading system to prevent information leakage.

### Audit Agent

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:university:audit-agent` |

**Role:** Education Compliance Audit Agent — verifies fair assessment through negative
provenance proof.

**Goal:** Verify that NO identity or demographic artifacts appear in the grading
dependency chain. Confirm isolation between grading and equity reporting workflows.
Produce audit report proving Article 13 compliance.

**Backstory:** Education regulatory compliance auditor specializing in AI fairness in
academic assessment. Looks for any possible pathway through which identity data could
have influenced grading decisions.

## Tasks

### Grading Flow

#### 1. Ingestion Task

**Agent:** ingestion_agent
**Input:** Student ID, essay topic, word count
**Output:** Anonymized essay text + identity data (clearly separated)

Receives essay submission and enforces blind grading by stripping all identity references
from the essay text. Outputs UserML observation layer with predicates: `word_count`,
`citation_count`, `structural_element`.

#### 2. Grading Task

**Agent:** grading_agent
**Input:** Essay text ONLY (no identity data)
**Output:** Envelope with UserML interpretation + application layers

Evaluates against rubric:
- Argument quality (30%)
- Evidence use (30%)
- Writing clarity (20%)
- Critical thinking (20%)

Uses predicates: `argument_quality`, `evidence_strength`, `writing_clarity`,
`critical_thinking` (interpretation); `overall_grade`, `grade_confidence`,
`rubric_weights` (application).

The `decision_influence` must reference ONLY content-based categories — never identity
attributes.

### Equity Flow

#### 3. Equity Task

**Agent:** equity_agent
**Input:** Aggregate demographics (e.g., 120 students, 52% F, 48% M, 35% first-gen)
**Output:** Aggregate equity report

Produces grade distribution statistics by demographic group with statistical significance
tests. This output has NO connection to individual grading decisions — no individual
student identifiers or grades linked to identities.

### Audit Flow

#### 4. Audit Task

**Agent:** audit_agent
**Input:** Both PROV graphs (grading + equity)
**Output:** Structured compliance audit report

Verifies two key properties:
1. **Negative proof** — identity artifacts are absent from the grading PROV dependency
   chain (recursive traversal)
2. **Workflow isolation** — equity reporting workflow has zero shared artifacts with
   grading workflow
3. **Implicit proxy risk** — checks for writing style or vocabulary patterns that could
   correlate with demographics

## PROV Graph Structure

Two completely isolated subgraphs:

```
Grading PROV (education_grading_prov.ttl):
  Agents:
    did:university:ingestion-agent
    did:university:grading-agent

  act-ingestion ────→ art-ingestion (TOKEN_SEQUENCE)
  act-grading ──────→ art-grading (SEMANTIC_EXTRACTION)
      └─ used: art-ingestion

  NO identity artifacts anywhere in this graph.


Equity PROV (education_equity_prov.ttl):
  Agents:
    did:university:equity-agent

  act-equity ───────→ art-equity (SEMANTIC_EXTRACTION)

  NO grading artifacts anywhere in this graph.
```

## Audit Checks

| Check | Article | What it proves |
|-------|---------|---------------|
| `workflow_isolation` | Art. 13 | Zero shared PROV entities between grading and equity graphs |
| `negative_proof` | Art. 13 | No `identity_data`, `demographic`, or `biometric` artifact types in the grading dependency chain |

## Output Files

| File | Description |
|------|-------------|
| `education_grading_envelope.json` | Grading flow envelope (2 artifacts) |
| `education_grading_prov.ttl` | Grading PROV graph — 2 agents, 2 activities |
| `education_grading_metrics.json` | Per-step timing for grading flow |
| `education_equity_prov.ttl` | Equity PROV graph — 1 agent, 1 activity |
| `education_audit.json` | Workflow isolation + negative proof + narrative audit |

## Running

```bash
python -m agent.run --local --scenario education
```

## Default Student

Student S-98765: essay on "The Role of Carbon Pricing in Climate Policy", 1500 words.
Aggregate demographics: 120 students, 52% female, 48% male, 35% first-generation.

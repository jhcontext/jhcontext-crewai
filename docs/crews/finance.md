# Finance Crew — Composite Compliance for Credit Assessment

EU AI Act Annex III 5(b) compliance scenario: a high-risk credit assessment system
combining ALL four PAC-AI compliance patterns — negative proof, temporal oversight,
workflow isolation, and PII detachment — the first scenario to demonstrate composite
compliance.

## Overview

| Property | Value |
|----------|-------|
| Risk Level | **HIGH** |
| Forwarding Policy | Semantic-Forward |
| Human Oversight | Required (credit officer review with temporal proof) |
| EU AI Act Articles | Annex III 5(b), Article 13 (Transparency), Article 14 (Human Oversight) |
| GDPR Articles | Article 22 (Right to Explanation), Articles 17/25 (PII Protection) |
| Other Regulation | EBA Guidelines on Loan Origination |
| Crews | 4 (Credit, Fair Lending, Oversight, Audit) |
| Total Agents | 7 |
| Total Tasks | 7 |
| Compliance Patterns | 4 (negative proof + temporal oversight + workflow isolation + PII detachment) |

## Regulatory Mapping

| Regulation | Article | Requirement | PAC-AI Evidence |
|------------|---------|-------------|-----------------|
| EU AI Act | Annex III, 5(b) | Credit scoring = HIGH-risk | `risk_level: high` in envelope |
| EU AI Act | Art. 13 | Transparency + explainability | Factor breakdown in `explanation_factors` |
| EU AI Act | Art. 14 | Meaningful human oversight | Temporal proof via PROV timestamps |
| GDPR | Art. 22 | Right to explanation | Decision factors in application layer |
| GDPR | Art. 5(c) | Data minimization | Semantic-Forward policy |
| GDPR | Arts. 17, 25 | PII protection / right to erasure | PII detachment + vault purge |
| EBA Guidelines | Loan origination | Model validation + human review | Full audit trail + oversight proof |

## Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                   FinanceCreditCrew                          │
│                                                             │
│   data_collector ──→ risk_analyzer ──→ decision_agent       │
│   (Haiku)            (Haiku)           (Sonnet)             │
│   art-financial-data art-risk-analysis art-credit-decision  │
│                                                             │
│   Semantic-Forward: each task reads only semantic_payload   │
│   PII detachment: tax_id, account_number tokenized          │
│   Negative proof: NO gender/ethnicity/age/nationality       │
└─────────────────────────┬───────────────────────────────────┘
                          │ AI credit recommendation
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                FinanceOversightCrew                          │
│                                                             │
│   credit_officer_agent (Sonnet) — senior officer review     │
│                                                             │
│   Code-controlled document access with real timestamps:     │
│     ├─ Access income verification ──── 3 sec review         │
│     ├─ Access employment records ───── 2 sec review         │
│     ├─ Access credit bureau report ─── 3 sec review         │
│     └─ Review AI recommendation ────── 2 sec review         │
│                                                             │
│   → art-oversight                                           │
└─────────────────────────┬───────────────────────────────────┘
                          │ oversight report
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  FinanceAuditCrew                            │
│                                                             │
│   audit_agent (Sonnet) — composite compliance verification  │
│                                                             │
│   Programmatic (SDK):                                       │
│     • verify_negative_proof() — Art. 13 check               │
│     • verify_temporal_oversight() — Art. 14 check           │
│     • verify_integrity() — envelope signature               │
│                                                             │
│   Narrative (LLM):                                          │
│     • Full composite compliance audit report                │
│                                                             │
│   → art-audit                                               │
└─────────────────────────────────────────────────────────────┘

                    ╳ ISOLATED ╳

┌─────────────────────────────────────────────────────────────┐
│              FinanceFairLendingCrew                          │
│                                                             │
│   fair_lending_agent (Haiku) — aggregate demographics only  │
│                                                             │
│   Separate context_id, separate PROV graph                  │
│   Zero shared artifacts with credit pipeline                │
│   → art-fair-lending                                        │
└─────────────────────────────────────────────────────────────┘

                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│               FinanceAuditFlow                              │
│                                                             │
│   Cross-workflow verification:                              │
│     • verify_workflow_isolation() — zero shared artifacts    │
│     • verify_negative_proof() — cross-workflow check        │
│     • Composite compliance: all 4 patterns verified         │
└─────────────────────────────────────────────────────────────┘
```

## Agents

### Data Collector Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (data extraction) |
| DID | `did:bank:data-collector-agent` |
| Artifact | `art-financial-data` (TOKEN_SEQUENCE) |

**Role:** Collects applicant financial data from banking systems. Explicitly excludes
all protected attributes (gender, ethnicity, marital status, nationality, age).

### Risk Analyzer Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (classification) |
| DID | `did:bank:risk-analyzer-agent` |
| Artifact | `art-risk-analysis` (SEMANTIC_EXTRACTION) |

**Role:** Computes DTI ratio, payment reliability, employment stability, default
probability. Works exclusively from financial variables in the semantic payload.

### Decision Agent

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:bank:decision-agent` |
| Artifact | `art-credit-decision` (SEMANTIC_EXTRACTION) |

**Role:** Produces credit decision with explainable factor breakdown as required by
EU AI Act Art. 13 and GDPR Art. 22. Lists every factor that influenced the decision.

### Credit Officer Agent

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:bank:credit-officer` |
| Artifact | `art-oversight` (SEMANTIC_EXTRACTION) |

**Role:** Simulates senior credit officer performing mandatory human review. Reviews
income docs, employment records, bureau report, and AI recommendation with timed access.

### Fair Lending Agent

| Property | Value |
|----------|-------|
| LLM | Claude Haiku (classification) |
| DID | `did:bank:fair-lending-agent` |
| Artifact | `art-fair-lending` (SEMANTIC_EXTRACTION) |

**Role:** Analyzes aggregate demographic statistics for disparate impact. Completely
isolated workflow — never accesses individual application data.

### Audit Agent

| Property | Value |
|----------|-------|
| LLM | Claude Sonnet (reasoning) |
| DID | `did:bank:audit-agent` |
| Artifact | `art-audit` (TOOL_RESULT) |

**Role:** Verifies composite compliance: negative proof, temporal oversight, workflow
isolation, integrity, PII detachment.

## Audit Checks

| Check | Article | What it proves |
|-------|---------|---------------|
| `negative_proof` | Art. 13 | Protected attributes (gender, ethnicity, marital status, nationality, age, religion) absent from credit decision PROV chain |
| `temporal_oversight` | Art. 14 | Credit officer reviewed 4 source documents AFTER AI recommendation, with meaningful review duration |
| `workflow_isolation` | Art. 13 | Fair lending workflow shares zero PROV entities with credit pipeline |
| `integrity` | Art. 15 | Envelope `content_hash` + Ed25519 `signature` valid |
| `composite_compliance` | All | All 4 patterns verified — first scenario to combine all compliance patterns |

## Output Files

| File | Description |
|------|-------------|
| `finance_envelopes.json` | Per-task envelopes from credit pipeline |
| `finance_credit_prov.ttl` | W3C PROV graph for credit assessment |
| `finance_fair_lending_prov.ttl` | W3C PROV graph for fair lending (isolated) |
| `finance_audit.json` | Programmatic checks + narrative audit + composite compliance |
| `finance_metrics.json` | Per-step timing |

## Running

```bash
python -m agent.run --local --scenario finance
```

## Default Application

Applicant APP-2026-00847: EUR 25,000 personal loan for home renovation. Monthly income
EUR 3,800 (permanent contract, 48 months tenure), existing monthly debt EUR 420, credit
bureau score 710, 96% on-time payment history.

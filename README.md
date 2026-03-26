# jhcontext-crewai

Production deployment of the **PAC-AI protocol** with CrewAI agents on AWS.

Multi-agent healthcare, education, recommendation, and finance scenarios that demonstrate
EU AI Act compliance (Annex III 5(b), Articles 13 and 14) through auditable context
envelopes, W3C PROV provenance graphs, and cryptographic integrity verification — all
persisted on DynamoDB + S3.

> **TL;DR:** This is the production-grade version of the jhcontext compliance scenarios — real CrewAI agents, AWS infrastructure (Chalice Lambda + DynamoDB + S3), and persistent storage. For a lightweight in-memory proof-of-concept with no infrastructure, see [jhcontext-usecases](../jhcontext-usecases/).

## Architecture

```
                          ┌─────────────────────────────┐
                          │     Agent (local/Lambda)     │
                          │  CrewAI Flows + ContextMixin │
                          └──────────┬──────────────────┘
                                     │ HTTPS
                    ┌────────────────┼────────────────┐
                    ▼                ▼                 ▼
         ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
         │  jhcontext-api│  │ jhcontext-mcp│  │   S3 Bucket  │
         │   (Chalice)   │  │   (Chalice)  │  │  artifacts   │
         │   Lambda      │  │   Lambda     │  └──────────────┘
         └───────┬───────┘  └───────┬──────┘
                 │                  │
         ┌───────┴──────────────────┴──────┐
         │           DynamoDB              │
         │  envelopes · artifacts · prov   │
         │  decisions (4 tables)           │
         └─────────────────────────────────┘
```

Three independent modules, three separate deployments. The agent runs locally and calls
the deployed API over HTTPS — keeping Lambda cold start under 2 seconds.

See [Architecture](docs/architecture.md) for full repository structure and dependency
separation.

## Scenarios (Crews)

Each scenario demonstrates a different EU AI Act compliance pattern:

| Scenario | Article | Risk | Agents | Key Proof |
|----------|---------|------|--------|-----------|
| [Healthcare](docs/crews/healthcare.md) | Art. 14 — Human Oversight | HIGH | 5 (sensor → situation → decision → oversight → audit) | Temporal proof that physician reviewed docs AFTER AI recommendation |
| [Education](docs/crews/education.md) | Art. 13 — Non-Discrimination | HIGH | 4 (ingestion → grading ╳ equity → audit) | Workflow isolation + negative proof (identity absent from grading) |
| [Recommendation](docs/crews/recommendation.md) | LOW-risk | LOW | 3 (profile → search → personalize) | Full provenance with Raw-Forward policy |
| [Finance](docs/crews/finance.md) | Annex III 5(b) — Composite | HIGH | 7 (data → risk → decision → oversight ╳ fair lending → audit) | All 4 patterns: negative proof + temporal oversight + workflow isolation + PII detachment |

## Crew Delegation in PROV

Crews are modeled explicitly in the W3C PROV graph using `prov:actedOnBehalfOf`. The
PROV graph itself serves as the coordination layer — no external pipeline ID needed.

In any flow, call `_register_crew()` after `_init_context()`:

```python
class MyFlow(Flow, ContextMixin):
    @start()
    def init(self):
        self._init_context(
            scope="healthcare",
            producer="did:hospital:system",
            risk_level=RiskLevel.HIGH,
        )

        # Agents in the crew get prov:actedOnBehalfOf the crew agent
        self._register_crew(
            crew_id="crew:clinical-pipeline",
            label="Clinical Pipeline Crew",
            agent_ids=[
                "did:hospital:sensor-agent",
                "did:hospital:situation-agent",
                "did:hospital:decision-agent",
            ],
        )
        # Oversight agent stays outside the crew — explicit boundary
```

This produces PROV triples like:

```turtle
jh:crew-clinical-pipeline a prov:Agent, prov:SoftwareAgent ;
    rdfs:label "Clinical Pipeline Crew" ;
    jh:agentType "crew" .

<did:hospital:sensor-agent> prov:actedOnBehalfOf jh:crew-clinical-pipeline .
```

Query all activities from a crew via SPARQL:

```sparql
SELECT ?activity ?label WHERE {
    ?agent prov:actedOnBehalfOf jh:crew-clinical-pipeline .
    ?activity prov:wasAssociatedWith ?agent .
    ?activity rdfs:label ?label .
}
```

## Quick Start

### Prerequisites

- Python 3.10+
- AWS account with credentials configured (`aws configure`)
- `jhcontext` SDK published to PyPI (or installed from `../jhcontext-sdk`)

### 1. Create DynamoDB tables and S3 bucket

```bash
cd jhcontext-crewai/api
pip install -r requirements.txt
python setup_tables.py
```

This creates 4 DynamoDB tables (PAY_PER_REQUEST billing) and 1 S3 bucket:
- `jhcontext-envelopes` (PK: context_id, GSI: ScopeIndex)
- `jhcontext-artifacts` (PK: artifact_id, GSI: ContextIndex)
- `jhcontext-prov-graphs` (PK: context_id)
- `jhcontext-decisions` (PK: decision_id, GSI: ContextIndex)
- `jhcontext-artifacts-dev` (S3 bucket for large artifact content)

### 2. Deploy API

```bash
cd jhcontext-crewai/api
./deploy.sh
```

Note the API endpoint URL printed at the end.

### 3. Deploy MCP (optional)

```bash
cd jhcontext-crewai/mcp
./deploy.sh
```

### 4. Install agent dependencies (local)

```bash
cd jhcontext-crewai
pip install -r agent/requirements.txt
```

Set the API URL:

```bash
export JHCONTEXT_API_URL=https://{api-id}.execute-api.us-east-1.amazonaws.com/api
```

## Running Scenarios

### With AWS

```bash
python -m agent.run --scenario healthcare
python -m agent.run --scenario education
python -m agent.run --scenario recommendation
python -m agent.run --scenario finance
python -m agent.run --scenario all
```

### Without AWS (local mode)

```bash
python -m agent.run --local --scenario healthcare
python -m agent.run --local --scenario all
```

Auto-starts a local SQLite server on `:8400`, runs the scenario, and shuts down. No
second terminal needed. See [Local Development](docs/local-development.md) for details.

### Validate results

```bash
python -m agent.run --validate        # validate latest run
python -m agent.run --validate v01    # validate specific run
```

See [Validation](docs/validation.md) for interpreting results, audit checks, and
UserML semantic payloads.

## Documentation

| Topic | Description |
|-------|-------------|
| [Architecture](docs/architecture.md) | System diagram, repository structure, dependency separation |
| [API Reference](docs/api-reference.md) | All API routes with curl examples |
| [Forwarding Policy](docs/forwarding-policy.md) | Semantic-Forward vs Raw-Forward, monotonic enforcement |
| [Understanding Run Output](docs/understanding-run-output.md) | How to read envelopes, PROV graphs, audits, metrics, and validation results |
| [Local Development](docs/local-development.md) | Running without AWS (SQLite backend) |
| [Security](docs/security.md) | API authentication roadmap (API key → IAM → Cognito → mTLS) |
| [Validation](docs/validation.md) | Protocol validation, audit checks, UserML, PROV, metrics |
| [Test Suite](tests/README.md) | Unit tests: storage backend, local mode, ontology validation |

### Crew Documentation

| Crew | Article | Description |
|------|---------|-------------|
| [Healthcare](docs/crews/healthcare.md) | Art. 14 | 5 agents, 3 crews, Semantic-Forward, temporal oversight proof |
| [Education](docs/crews/education.md) | Art. 13 | 4 agents, 3 isolated flows, workflow isolation + negative proof |
| [Recommendation](docs/crews/recommendation.md) | LOW-risk | 3 agents, 1 crew, Raw-Forward, full provenance |
| [Finance](docs/crews/finance.md) | Annex III 5(b) | 7 agents, 4 crews, composite compliance (all 4 patterns) |

### Scenario Diagrams

Reference figures from the PAC-AI paper (IADIS AIS 2026):

| Figure | Scenario | Description |
|--------|----------|-------------|
| ![Healthcare](docs/imgs/healthcare-oversight.jpeg) | Healthcare (Art. 14) | Temporal provenance proving meaningful human oversight — physician accessed source documents independently before reviewing AI recommendation |
| ![Education](docs/imgs/education.jpg) | Education (Art. 13) | Negative provenance proof — two isolated subgraphs show grading used only text/rubric (no identity data) |

## License

Apache 2.0

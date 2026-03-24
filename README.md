# jhcontext-crewai

Production deployment of the **PAC-AI protocol** with CrewAI agents on AWS.

Multi-agent healthcare, education, and recommendation scenarios that demonstrate EU AI Act
compliance (Articles 13 and 14) through auditable context envelopes, W3C PROV provenance
graphs, and cryptographic integrity verification — all persisted on DynamoDB + S3.

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
| [Local Development](docs/local-development.md) | Running without AWS (SQLite backend) |
| [Security](docs/security.md) | API authentication roadmap (API key → IAM → Cognito → mTLS) |
| [Validation](docs/validation.md) | Protocol validation, audit checks, UserML, PROV, metrics |

### Crew Documentation

| Crew | Article | Description |
|------|---------|-------------|
| [Healthcare](docs/crews/healthcare.md) | Art. 14 | 5 agents, 3 crews, Semantic-Forward, temporal oversight proof |
| [Education](docs/crews/education.md) | Art. 13 | 4 agents, 3 isolated flows, workflow isolation + negative proof |
| [Recommendation](docs/crews/recommendation.md) | LOW-risk | 3 agents, 1 crew, Raw-Forward, full provenance |

## License

Apache 2.0

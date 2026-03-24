# Architecture

## System Diagram

```
                          ┌─────────────────────────────┐
                          │     Agent (local/Lambda)     │
                          │  CrewAI Flows + ContextMixin │
                          │  pip install -r agent/req.   │
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

**Three independent modules, three separate deployments:**

| Module | Runtime | Dependencies | Lambda size |
|--------|---------|-------------|-------------|
| `api/` | Lambda via Chalice | `jhcontext + chalice + boto3` | ~15 MB |
| `mcp/` | Lambda via Chalice | `jhcontext + chalice + boto3` | ~15 MB |
| `agent/` | **Local** (or Lambda worker) | `crewai + crewai-tools + jhcontext + httpx` | ~500 MB (not on Lambda) |

The agent never ships to Lambda alongside the API — it runs locally and calls the
deployed API over HTTPS. This keeps the Lambda cold start under 2 seconds.

## Repository Structure

```
jhcontext-crewai/
├── api/                              # Chalice REST API (Lambda + API Gateway)
│   ├── app.py                        # Chalice app — 11 routes
│   ├── .chalice/config.json          # Lambda config (256 MB, 30s timeout)
│   ├── chalicelib/
│   │   ├── routes/                   # Route handlers (5 modules)
│   │   │   ├── envelopes.py          # POST/GET /envelopes
│   │   │   ├── artifacts.py          # POST/GET /artifacts
│   │   │   ├── provenance.py         # POST/GET /provenance + /provenance/query
│   │   │   ├── decisions.py          # POST/GET /decisions
│   │   │   └── compliance.py         # GET /compliance/package/{id} (ZIP export)
│   │   └── storage/
│   │       └── dynamodb.py           # DynamoDB + S3 StorageBackend (9 methods)
│   ├── setup_tables.py               # Creates 4 DynamoDB tables + S3 bucket
│   ├── deploy.sh                     # Deploys API Lambda
│   └── requirements.txt              # API-only deps (lightweight)
│
├── agent/                            # CrewAI flows (runs locally)
│   ├── protocol/
│   │   └── context_mixin.py          # CrewAI ↔ PAC-AI bridge mixin (forwarding policy)
│   ├── ontologies/                   # Domain-specific UserML predicates
│   │   ├── healthcare.py
│   │   ├── education.py
│   │   ├── recommendation.py
│   │   └── validator.py
│   ├── crews/
│   │   ├── healthcare/               # 3+2 agents: clinical crew + oversight + audit
│   │   ├── education/                # 4 agents: ingestion + grading + equity + audit
│   │   └── recommendation/           # 3 agents: profile → search → personalize
│   ├── flows/
│   │   ├── healthcare_flow.py        # Article 14 — human oversight with temporal proof
│   │   ├── education_flow.py         # Article 13 — negative proof + workflow isolation
│   │   └── recommendation_flow.py    # LOW-risk — Raw-Forward product recommendations
│   ├── run.py                        # Entry point: python -m agent.run --scenario ...
│   └── requirements.txt              # Agent deps (crewai — never on Lambda)
│
├── mcp/                              # MCP HTTP proxy (separate Lambda)
│   ├── app.py                        # Chalice app — /mcp POST endpoint
│   ├── .chalice/config.json
│   ├── chalicelib/
│   │   └── dynamodb_storage.py       # Synced from api/ at deploy time
│   ├── deploy.sh                     # Deploys MCP Lambda
│   └── requirements.txt              # MCP-only deps (lightweight)
│
├── docs/                             # Documentation
│   ├── crews/                        # Per-crew documentation
│   │   ├── healthcare.md
│   │   ├── education.md
│   │   └── recommendation.md
│   ├── architecture.md               # This file
│   ├── api-reference.md              # API routes + curl examples
│   ├── forwarding-policy.md          # Semantic-Forward vs Raw-Forward
│   ├── local-development.md          # Running without AWS
│   ├── security.md                   # API authentication roadmap
│   └── validation.md                 # Protocol validation + UserML + PROV
│
├── output/                           # Generated artifacts (gitignored)
│   ├── runs/v01/, v02/, ...          # Versioned run outputs
│   └── latest → runs/vNN/           # Symlink to most recent
│
├── tests/                            # Test suite
├── pyproject.toml                    # Root package config
└── README.md
```

## Dependency Separation

This is critical for Lambda deployment size:

```
api/requirements.txt          →  jhcontext + chalice + boto3          (~15 MB)
mcp/requirements.txt          →  jhcontext + chalice + boto3          (~15 MB)
agent/requirements.txt        →  jhcontext + httpx + crewai + tools   (~500 MB)
```

- **API Lambda** and **MCP Lambda** each deploy under 50 MB (Chalice ZIP limit).
- **Agent** runs locally (or as a separate Lambda worker via SQS if needed for production).
- `pyproject.toml` optional groups (`[api]`, `[agent]`) mirror this separation.
- **Never** add `crewai` to `api/requirements.txt` or `mcp/requirements.txt`.

### Why MCP is a separate Lambda

The MCP handler uses `jhcontext.prov.PROVGraph` (which pulls in `rdflib` ~8 MB). While
the API also uses `rdflib` via provenance routes, keeping MCP as a separate Lambda means:
- Independent scaling and cold starts
- MCP can be versioned/deployed independently
- Future: MCP could use Streamable HTTP transport for bidirectional communication
- The `mcp/deploy.sh` syncs `dynamodb_storage.py` from `api/` to keep one source of truth

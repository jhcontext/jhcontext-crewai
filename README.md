# jhcontext-crewai

Production deployment of the **PAC-AI protocol** with CrewAI agents on AWS.

Multi-agent healthcare and education scenarios that demonstrate EU AI Act compliance
(Articles 13 and 14) through auditable context envelopes, W3C PROV provenance graphs,
and cryptographic integrity verification — all persisted on DynamoDB + S3.

## Architecture

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
│   ├── crews/
│   │   ├── healthcare/               # 3+2 agents: clinical crew + oversight + audit
│   │   │   ├── config/agents.yaml
│   │   │   ├── config/tasks.yaml
│   │   │   └── crew.py              # HealthcareClinicalCrew (3 tasks, Semantic-Forward)
│   │   ├── recommendation/           # 3 agents: profile→search→personalize
│   │   │   ├── config/agents.yaml
│   │   │   ├── config/tasks.yaml
│   │   │   └── crew.py              # RecommendationCrew (3 tasks, Raw-Forward)
│   │   └── education/                # 4 agents: ingestion→grading→equity→audit
│   │       ├── config/agents.yaml
│   │       ├── config/tasks.yaml
│   │       └── crew.py
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
├── output/                           # Generated artifacts (gitignored)
├── pyproject.toml                    # Root package config
└── README.md
```

## Prerequisites

- Python 3.10+
- AWS account with credentials configured (`aws configure`)
- `jhcontext` SDK published to PyPI (or installed from `../jhcontext-sdk`)

## Setup

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

## Testing the API with curl

After deploying, replace `$API` with your endpoint URL:

```bash
API=https://{api-id}.execute-api.us-east-1.amazonaws.com/api
```

### Health check

```bash
curl $API/health
# {"status": "ok", "service": "jhcontext-api", "version": "0.2.0"}
```

### Submit an envelope

```bash
curl -X POST $API/envelopes \
  -H "Content-Type: application/json" \
  -d '{
    "envelope": {
      "context_id": "ctx-test-001",
      "schema_version": "jh:0.3",
      "producer": "did:hospital:test",
      "scope": "healthcare_test",
      "status": "active",
      "compliance": {
        "risk_level": "high",
        "human_oversight_required": true,
        "forwarding_policy": "semantic_forward"
      },
      "proof": {
        "content_hash": "abc123"
      }
    }
  }'
# {"context_id": "ctx-test-001", "content_hash": "abc123"}
```

### Retrieve an envelope (JSON-LD)

```bash
curl $API/envelopes/ctx-test-001
# Returns full envelope with @context and @type JSON-LD annotations
```

### List envelopes (with filters)

```bash
curl "$API/envelopes?scope=healthcare_test"
curl "$API/envelopes?risk_level=high"
```

### Upload an artifact (base64 content)

```bash
# Encode content
CONTENT=$(echo -n "Patient P-12345: elevated tumor markers" | base64)

curl -X POST $API/artifacts \
  -H "Content-Type: application/json" \
  -d "{
    \"artifact_id\": \"art-sensor-test\",
    \"context_id\": \"ctx-test-001\",
    \"artifact_type\": \"token_sequence\",
    \"content_base64\": \"$CONTENT\"
  }"
# {"artifact_id": "art-sensor-test", "content_hash": "...", "storage_path": "s3://..."}
```

### Retrieve an artifact

```bash
curl $API/artifacts/art-sensor-test
# {"artifact_id": "art-sensor-test", "type": "token_sequence",
#  "content_hash": "...", "content_base64": "..."}
```

### Submit a PROV graph (Turtle format)

```bash
curl -X POST $API/provenance \
  -H "Content-Type: application/json" \
  -d '{
    "context_id": "ctx-test-001",
    "graph_turtle": "@prefix prov: <http://www.w3.org/ns/prov#> .\n@prefix jh: <https://jhcontext.com/vocab#> .\n\njh:art-sensor a prov:Entity ;\n    prov:wasGeneratedBy jh:act-sensor .\njh:act-sensor a prov:Activity .\njh:agent-sensor a prov:Agent .\njh:act-sensor prov:wasAssociatedWith jh:agent-sensor .\n"
  }'
# {"context_id": "ctx-test-001", "digest": "...", "path": "ctx-test-001"}
```

### Query provenance (causal chain, temporal sequence)

```bash
# Temporal sequence — shows all activities in order
curl -X POST $API/provenance/query \
  -H "Content-Type: application/json" \
  -d '{
    "context_id": "ctx-test-001",
    "query_type": "temporal_sequence"
  }'

# Causal chain — traces what generated a specific entity
curl -X POST $API/provenance/query \
  -H "Content-Type: application/json" \
  -d '{
    "context_id": "ctx-test-001",
    "query_type": "causal_chain",
    "entity_id": "art-sensor"
  }'
```

### Log a decision

```bash
curl -X POST $API/decisions \
  -H "Content-Type: application/json" \
  -d '{
    "context_id": "ctx-test-001",
    "passed_artifact_id": "art-sensor-test",
    "outcome": {"recommendation": "Continue chemotherapy", "confidence": 0.87},
    "agent_id": "did:hospital:decision-agent"
  }'
# {"decision_id": "dec-..."}
```

### Export compliance package (ZIP)

```bash
curl $API/compliance/package/ctx-test-001 -o compliance.zip
# Downloads ZIP containing: envelope.json, provenance.ttl, audit_report.json, manifest.json
```

### Test MCP endpoint

```bash
MCP=https://{mcp-id}.execute-api.us-east-1.amazonaws.com/api

curl $MCP/health

curl -X POST $MCP/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "get_envelope",
    "arguments": {"context_id": "ctx-test-001"}
  }'

curl -X POST $MCP/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "run_audit",
    "arguments": {"context_id": "ctx-test-001", "checks": ["integrity"]}
  }'
```

## Forwarding Policy

The protocol supports two deployment patterns for inter-task data flow, controlled by
`compliance.forwarding_policy` in each task's envelope output:

| Policy | Description | Risk Level |
|--------|-------------|------------|
| `semantic_forward` | Next task receives **only** `semantic_payload` — structured, auditable semantic extractions. Raw tokens/vectors/embeddings are stripped from the context before the next task runs. | Required for HIGH |
| `raw_forward` | Next task receives the full envelope (all fields). Faster, but audit trail may diverge from what the agent actually consumed. | Permitted for LOW/MEDIUM |

**Key properties:**

- **Per-task granularity** — each task controls its own forwarding via the envelope it outputs.
  A fetch task can use `raw_forward` while the downstream classification task switches to
  `semantic_forward`.
- **Monotonic enforcement** — once any task in a crew sets `semantic_forward`, subsequent
  tasks **cannot downgrade** to `raw_forward`. The `ContextMixin._resolve_forwarding_policy()`
  tracks this boundary in flow state. Violations are overridden with a logged warning.
- **Full persistence regardless** — the callback persists the **complete envelope** (with all
  artifact metadata) to the backend API, even when the next task only sees `semantic_payload`.
  Nothing is lost for audit — raw artifacts are always in the backend for debugging.
- **Envelope-driven** — the `forwarding_policy` is a first-class field in the `ComplianceBlock`,
  not a prompt instruction. The `EnvelopeBuilder.set_risk_level(HIGH)` auto-sets
  `semantic_forward`; `set_risk_level(LOW)` auto-sets `raw_forward`. Tasks can override
  via their YAML-instructed envelope output.

### Healthcare example (mixed forwarding)

```
sensor_task  (raw_forward)      →  output.raw = full envelope (all observations)
                                        ↓  situation_task sees everything
situation_task (semantic_forward) →  output.raw = {"semantic_payload": [...]} ONLY
                                        ↓  decision_task sees only semantic data
decision_task (semantic_forward)  →  only semantic_payload visible
```

The **semantic boundary** is at the classification step (situation_task). Before it, raw data
flows freely for ingestion. After it, only structured semantic extractions are visible to
decision-making tasks — enforced structurally, not by prompt.

### Task preamble injection

The `ContextMixin._get_forwarding_preamble()` method generates a constraint instruction from
the flow-level envelope's forwarding policy. This preamble is passed to `crew.kickoff(inputs=...)`
and interpolated into task descriptions via `{_forwarding_preamble}` placeholders in YAML.
For Semantic-Forward flows, tasks receive an explicit instruction to read only `semantic_payload`.
For Raw-Forward, the preamble is empty.

## Running Agent Scenarios

### Healthcare — Article 14 Human Oversight (Semantic-Forward)

```bash
export JHCONTEXT_API_URL=https://{api-id}.execute-api.us-east-1.amazonaws.com/api
cd jhcontext-crewai
python -m agent.run --scenario healthcare
```

Pipeline: `sensor → situation → decision` (single multi-task crew) `→ oversight → audit`

The clinical pipeline runs as a single `HealthcareClinicalCrew` with 3 agents and 3 tasks.
Each task outputs a full jhcontext Envelope with `output_pydantic=Envelope`. The
`_persist_task_callback` fires after each task to:
1. Resolve the effective forwarding policy (per-task with monotonic enforcement)
2. Rewrite `output.raw` for Semantic-Forward tasks (strip everything except `semantic_payload`)
3. Persist the full envelope + PROV graph to the backend in a background thread

Physician oversight and audit run as separate single-task crews (regulatory isolation).

**Outputs** (in `output/`):
- `healthcare_envelope.json` — complete JSON-LD envelope with all artifacts + `forwarding_policy`
- `healthcare_prov.ttl` — W3C PROV graph (Turtle) showing the full decision chain
- `healthcare_audit.json` — Article 14 compliance audit results
- `healthcare_metrics.json` — per-step timing (envelope generation, persist latency)

### Education — Article 13 Non-Discrimination

```bash
python -m agent.run --scenario education
```

Runs **three isolated workflows**:
1. **Grading** (ingestion → blind grading) — no identity data in PROV chain
2. **Equity reporting** (separate workflow) — aggregate demographics only
3. **Audit** — verifies zero shared artifacts between grading and equity workflows

**Outputs**:
- `education_grading_envelope.json` + `education_grading_prov.ttl`
- `education_equity_prov.ttl`
- `education_audit.json` — negative proof + workflow isolation results

### Recommendation — LOW-Risk Product Recommendations (Raw-Forward)

```bash
python -m agent.run --scenario recommendation
```

Pipeline: `profile → search → personalize` (single multi-task crew, no oversight)

Demonstrates Raw-Forward: all 3 tasks use `raw_forward` — agents consume the full
aggregated context (CrewAI default). No semantic boundary is crossed. Protocol persistence
still records full envelopes + PROV for traceability, but without the Semantic-Forward
constraint.

**Outputs**:
- `recommendation_envelope.json` — envelope with `forwarding_policy: "raw_forward"`
- `recommendation_prov.ttl` — PROV graph
- `recommendation_output.json` — final recommendations
- `recommendation_metrics.json` — per-step timing

### Run all scenarios

```bash
python -m agent.run --scenario all
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

## Securing the API and MCP

The current deployment is **open** (no authentication) — appropriate for a research
prototype. Below is the security roadmap for production hardening.

### Phase 1: API Key Authentication (Immediate)

Add an API key check to protect the endpoints from unauthorized access:

```python
# api/app.py — add to each route or create a middleware
API_KEY = os.environ.get("JHCONTEXT_API_KEY")

def require_api_key(app):
    if API_KEY:
        auth = app.current_request.headers.get("Authorization", "")
        if auth != f"Bearer {API_KEY}":
            raise UnauthorizedError("Invalid API key")
```

Set in `.chalice/config.json`:
```json
"environment_variables": {
    "JHCONTEXT_API_KEY": "{{ssm:/jhcontext/api-key}}"
}
```

The agent's `JHContextClient` already supports `api_key` parameter:
```python
client = JHContextClient(base_url=API_URL, api_key="your-key")
```

### Phase 2: IAM Authorization (Recommended for AWS-native)

Use API Gateway IAM authorization — the agent signs requests with AWS SigV4:

```json
// .chalice/config.json
"stages": {
  "prod": {
    "api_gateway_policy": {
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"AWS": "arn:aws:iam::ACCOUNT:role/jhcontext-agent-role"},
        "Action": "execute-api:Invoke",
        "Resource": "arn:aws:execute-api:*:*:*/api/*"
      }]
    }
  }
}
```

This is the strongest option for AWS-to-AWS communication:
- No API keys to rotate
- Automatic credential rotation via IAM roles
- Fine-grained resource-level policies (e.g., agent can POST envelopes but not DELETE)
- CloudTrail audit log of every API call

### Phase 3: Cognito JWT (If Multi-Tenant)

If multiple agents or tenants need separate access:

```python
# Same pattern as vendia-api — Chalice built-in JWT authorizer
@app.route("/envelopes", methods=["POST"], cors=True,
           authorizer=CognitoUserPoolAuthorizer("JHContextPool",
               provider_arns=["arn:aws:cognito-idp:..."],
               header="Authorization"))
```

### Phase 4: mTLS (For Paper / Compliance)

The jhcontext SDK already supports mutual TLS:

```python
client = JHContextClient(
    base_url=API_URL,
    tls_cert="/path/to/agent.crt",
    tls_key="/path/to/agent.key",
)
```

API Gateway supports custom domains with mutual TLS. This proves the agent identity
cryptographically — valuable for the paper's security claims.

### MCP-Specific Security

The MCP endpoint (`/mcp`) accepts arbitrary tool calls. Secure it:

1. **Separate API key** from the REST API (different `JHCONTEXT_MCP_KEY` env var)
2. **Tool allowlisting** — only allow specific tools per client
3. **Rate limiting** — API Gateway throttling (e.g., 10 req/sec per key)
4. **Input validation** — the MCP handler already validates tool_name; add payload size limits

```json
// mcp/.chalice/config.json
"stages": {
  "prod": {
    "api_gateway_endpoint_type": "PRIVATE",
    "api_gateway_endpoint_vpce": ["vpce-abc123"]
  }
}
```

Making MCP a **private endpoint** (VPC-only) is the strongest option if the agent runs
in the same VPC — no public internet exposure at all.

## Agent ↔ API Communication Best Practices

### Protocol Package Pattern

After a scenario completes, the agent can export a **compliance package** — a self-contained
ZIP containing everything needed for an audit:

```bash
# Export compliance package for a completed scenario
curl $API/compliance/package/ctx-healthcare-001 -o compliance_healthcare.zip
```

The package contains:
- `envelope.json` — complete JSON-LD envelope with all artifacts, hashes, signatures
- `provenance.ttl` — W3C PROV graph (machine-readable, queryable)
- `audit_report.json` — automated compliance check results
- `manifest.json` — package integrity metadata (envelope hash, PROV digest, timestamp)

### Best Practices for Agent → API Communication

**1. Envelope-per-flow, not envelope-per-task**

Each CrewAI Flow creates one envelope with one `context_id`. All tasks within
the flow add artifacts to the same envelope. This keeps the audit trail
self-contained:

```
Flow: HealthcareFlow
  └─ Envelope: ctx-healthcare-001
       ├─ art-sensor        (TOKEN_SEQUENCE)
       ├─ art-situation     (SEMANTIC_EXTRACTION)
       ├─ art-decision      (SEMANTIC_EXTRACTION)
       ├─ art-oversight     (SEMANTIC_EXTRACTION)
       └─ art-audit         (TOOL_RESULT)
```

**2. `passed_artifact_pointer` for inter-agent handoff**

The `passed_artifact_pointer` field in the envelope always points to the latest
artifact. When Agent B starts, it reads the envelope and knows which artifact
to consume — this is the auditable data handoff:

```
Agent A finishes → envelope.passed_artifact_pointer = "art-situation"
Agent B starts   → reads envelope → consumes art-situation
```

**3. Large artifacts go to S3, not the envelope**

The envelope stays small (~5 KB). If a task output exceeds 100 KB (embeddings,
token sequences, documents), the `ContextMixin._persist_step()` automatically
uploads to S3 via `POST /artifacts` and stores the `storage_ref` in the
envelope's artifact registry:

```json
{
  "artifact_id": "art-embedding",
  "type": "embedding",
  "content_hash": "sha256:...",
  "storage_ref": "s3://jhcontext-artifacts-dev/artifacts/art-embedding"
}
```

**4. Sign before persist**

The `ContextMixin` signs the envelope with the agent's DID before submitting.
Each re-submission (after each step) re-signs with the latest agent ID. The
`proof.content_hash` allows downstream verification that the envelope hasn't
been tampered with.

**5. Task-level persistence with forwarding policy enforcement**

For task-level persistence (within a crew), use `_persist_task_callback` as
CrewAI's `task_callback`. It runs in two phases:

- **Synchronous** — resolves the effective forwarding policy from the task's
  envelope (with monotonic enforcement), rewrites `output.raw` for Semantic-Forward
  tasks, and extends the flow-level builder + PROV graph.
- **Async** — persists the full envelope + PROV to the backend in a background
  thread so the next task isn't blocked by API latency.

```python
crew_instance = MyCrew().crew()
crew_instance.task_callback = self._persist_task_callback

preamble = self.state["_forwarding_preamble"]
result = crew_instance.kickoff(inputs={
    **input_data,
    "_forwarding_preamble": preamble,
})
```

### Best Practices for API → Agent Results

**1. Pull model, not push**

The agent pulls context from the API when needed (`GET /envelopes/{id}`),
rather than the API pushing to the agent. This keeps the API stateless and
the agent in control of timing.

**2. Compliance package as the deliverable**

After a flow completes, the canonical output is the compliance package
(`GET /compliance/package/{context_id}`). This is what goes to:
- Regulatory auditors (ZIP download)
- Institutional compliance databases (machine-readable JSON-LD + PROV)
- The paper's evidence section (envelope + PROV graph + audit results)

**3. Cross-service protocol transport**

If agents run on different services (Lambda A and Lambda B), the protocol
becomes the actual data transport — not just an audit trail:

```
Lambda A: Agent-1 → POST /envelopes → DynamoDB
Lambda B: Agent-2 → GET /envelopes/{id} → reads passed_artifact_pointer → fetches artifact
```

This is the production pattern for distributed multi-agent systems. The
envelope serves as both the context carrier and the audit record.

**4. Idempotent envelope updates**

The API uses `PUT` semantics (DynamoDB `put_item`) for envelope saves. Re-submitting
the same envelope with updated artifacts is safe — the latest version wins.
The PROV graph accumulates activities (each `POST /provenance` replaces the full graph).

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

The `validate.py` script checks that LLM-generated payloads conform to these vocabularies.

## PROV Graph Validation

Each scenario produces a W3C PROV graph (Turtle format) that captures the causal history of
every artifact: which agents performed which activities, using which inputs, to produce
which outputs.

### Healthcare PROV Structure (Article 14)

The healthcare scenario records **fine-grained oversight events** — each document the
physician accesses is a separate PROV activity with real timestamps:

```
act-sensor ──────────── agent: did:hospital:sensor-agent
  └→ art-sensor (TOKEN_SEQUENCE)

act-situation ──────── agent: did:hospital:situation-agent
  ├→ used: art-sensor
  └→ art-situation (SEMANTIC_EXTRACTION)

act-decision ──────── agent: did:hospital:decision-agent
  ├→ used: art-situation
  └→ art-decision (SEMANTIC_EXTRACTION)

act-access-ct-scan ── agent: did:hospital:dr-chen     ← 4s review
act-access-history ── agent: did:hospital:dr-chen     ← 3s review
act-access-pathology  agent: did:hospital:dr-chen     ← 2s review
act-review-ai ─────── agent: did:hospital:dr-chen     ← 1s review

act-oversight ──────── agent: did:hospital:dr-chen
  ├→ used: ent-ct-scan, ent-treatment-history, ent-pathology, ent-ai-recommendation
  └→ art-oversight (SEMANTIC_EXTRACTION)
```

This structure enables `verify_temporal_oversight()` to confirm:
- All 4 human review activities occur AFTER the AI recommendation
- Total review duration is meaningful (not rubber-stamping)

### Education PROV Structure (Article 13)

Two completely isolated subgraphs with zero shared entities:

```
Grading Workflow:                    Equity Workflow:
  art-ingestion → art-grading          art-equity (separate context_id)
  NO identity artifacts                NO grading artifacts
```

Validated by:
- `verify_workflow_isolation(grading_prov, equity_prov)` — zero shared entities
- `verify_negative_proof(grading_prov, "art-grading", ["identity_data", ...])` — identity absent

### SDK Audit Functions → EU AI Act Mapping

| Function | Article | Scenario | Verifies |
|----------|---------|----------|----------|
| `verify_temporal_oversight()` | Art. 14 | Healthcare | Physician reviewed source docs (not just AI summary) |
| `verify_negative_proof()` | Art. 13 | Education | Identity data absent from grading chain |
| `verify_workflow_isolation()` | Art. 13 | Education | Zero shared artifacts between workflows |
| `verify_integrity()` | Art. 15 | All | Envelope hash + signature valid |
| `verify_pii_detachment()` | GDPR | Optional | No PII remains in stored payload |

## Protocol Validation

After running scenarios, use `--validate` to produce a structured validation report
matching the paper's tables.

### Running Scenarios + Validation

Each run is saved to a versioned directory (`output/runs/v01/`, `v02/`, etc.):

```bash
# Run all scenarios (creates output/runs/v01/)
python -m agent.run --local --scenario all

# Validate the latest run
python -m agent.run --validate

# Validate a specific run
python -m agent.run --validate v01
```

### Run Directory Structure

```
output/
├── runs/
│   ├── v01/                              ← first run
│   │   ├── healthcare_envelope.json      ← full JSON-LD envelope
│   │   ├── healthcare_prov.ttl           ← W3C PROV graph (Turtle)
│   │   ├── healthcare_audit.json         ← programmatic + narrative audit
│   │   ├── healthcare_metrics.json       ← per-step timing
│   │   ├── education_grading_envelope.json
│   │   ├── education_grading_prov.ttl
│   │   ├── education_equity_prov.ttl
│   │   ├── education_audit.json
│   │   ├── recommendation_envelope.json
│   │   ├── recommendation_prov.ttl
│   │   ├── validation_report.json        ← full machine-readable report
│   │   └── summary.md                    ← human-readable interpretation
│   ├── v02/                              ← second run
│   │   └── ...
│   └── ...
└── latest → runs/v02/                    ← symlink to most recent run
```

Runs are **committed to git** so results are versioned alongside the code.

### Interpreting Results

Each run's `summary.md` contains a full interpretation guide. The key checks:

| Check | Article | Scenario | What it proves |
|-------|---------|----------|---------------|
| `temporal_oversight` | Art. 14 | Healthcare | Physician accessed 4 source documents AFTER AI recommendation, with meaningful review duration |
| `integrity` | Art. 15 | All | Envelope hash + signature are valid (tamper-evidence) |
| `workflow_isolation` | Art. 13 | Education | Zero shared PROV entities between grading and equity workflows |
| `negative_proof` | Art. 13 | Education | No identity/demographic artifacts in the grading dependency chain |
| `semantic_conformance` | — | All | Semantic payload uses valid UserML predicates from domain ontology |
| `risk_level` | Art. 9 | All | Envelope risk tier matches expected value |
| `forwarding_policy` | — | All | Forwarding policy matches expected pattern (semantic/raw) |

- **PASS** — check succeeded against the protocol specification
- **FAIL** — violation found (details in `validation_report.json`)
- **n/a** — check does not apply to this scenario

### Semantic Payload Conformance

This check verifies LLM agents produced payloads in UserML format with valid domain
predicates from `agent/ontologies/`. Failures mean the LLM wrote free-form JSON instead
of structured UserML — the protocol still functions, but payloads are not formally typed.
Use `FlatEnvelope` with `output_pydantic` to enforce stricter structure (see jhcontext-sdk
README).

## Local Development (Without AWS)

The entire project runs locally without AWS credentials, DynamoDB, S3, or Lambda.
The agent communicates via HTTP — it doesn't care whether the backend is DynamoDB or
SQLite. All you need is a local server.

### Quick Start (single command)

```bash
cd jhcontext-crewai
python -m agent.run --local --scenario healthcare
```

This auto-starts a local server (SQLite backend), runs the scenario, saves outputs
to `output/`, and shuts down the server when done. No second terminal needed.

### How It Works

```
LOCAL MODE (--local):
┌──────────────────────────────────────────────┐
│ Local Server (auto-started subprocess)       │
│  SQLiteStorage → ~/.jhcontext-crewai/data.db    │
│  Artifacts     → ~/.jhcontext-crewai/artifacts/ │
│  PII Vault     → ~/.jhcontext-crewai/pii_vault.db │
│  Listening on :8400                          │
└───────────────────┬──────────────────────────┘
                    │ HTTP (localhost:8400)
┌───────────────────▼──────────────────────────┐
│ Agent (same process/terminal)                │
│  CrewAI Flows → JHContextClient(httpx)       │
│  JHCONTEXT_API_URL=http://localhost:8400     │
└──────────────────────────────────────────────┘

AWS MODE (deployed):
┌──────────────────────────────────────────────┐
│ Lambda: Chalice API                          │
│  DynamoDBStorage → jhcontext-* tables        │
│  Artifacts       → S3 bucket                 │
│  PII Vault       → jhcontext-pii-vault table │
│  API Gateway :443                            │
└───────────────────┬──────────────────────────┘
                    │ HTTPS
┌───────────────────▼──────────────────────────┐
│ Agent (local or Lambda worker)               │
│  JHCONTEXT_API_URL=https://{api-id}...       │
└──────────────────────────────────────────────┘
```

The agent layer is **identical** in both modes — only the server backend differs.

### Two Local Modes

#### 1. `--local` flag (recommended for agent development)

```bash
python -m agent.run --local --scenario healthcare
python -m agent.run --local --scenario all
python -m agent.run --local --scenario all && python -m agent.run --validate
```

The `--local` flag:
1. Tries `chalice local` first (if Chalice is installed) — uses the actual Chalice API routes with SQLite
2. Falls back to the SDK's FastAPI server (via `uvicorn`) — same routes, same interface
3. Polls `/health` until ready, runs your scenarios, terminates on exit

#### 2. `JHCONTEXT_LOCAL=1 chalice local` (for API development)

```bash
cd jhcontext-crewai/api
JHCONTEXT_LOCAL=1 chalice local --port 8400
```

This starts the **actual Chalice API** with SQLite storage. Useful for:
- Testing API routes directly with `curl`
- Debugging route handler logic
- Running the agent in a separate terminal against it:
  ```bash
  # Terminal 2:
  export JHCONTEXT_API_URL=http://localhost:8400
  python -m agent.run --scenario healthcare
  ```

#### 3. SDK server (manual, two terminals)

```bash
# Terminal 1:
cd ~/Repos/jhcontext-sdk
uvicorn jhcontext.server.app:create_app --factory --port 8400

# Terminal 2:
cd ~/Repos/jhcontext-crewai
export JHCONTEXT_API_URL=http://localhost:8400
python -m agent.run --scenario healthcare
```

### Storage Backends

| Mode | Envelopes | PII Vault | Artifacts | Config |
|------|-----------|-----------|-----------|--------|
| **AWS** (deployed) | DynamoDB | DynamoDB (separate table) | S3 | `.chalice/config.json` env vars |
| **Chalice local** | SQLite `~/.jhcontext-crewai/data.db` | SQLite `pii_vault.db` | Filesystem `~/.jhcontext-crewai/artifacts/` | `JHCONTEXT_LOCAL=1` |
| **SDK server** | SQLite `~/.jhcontext/data.db` | SQLite `pii_vault.db` | Filesystem `~/.jhcontext/artifacts/` | SDK defaults |

Both SQLite backends implement the **exact same StorageBackend protocol** as DynamoDB —
same 9 methods, same semantics, same return types.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JHCONTEXT_LOCAL` | _(unset)_ | Set to `1` to switch Chalice API to SQLite backend |
| `JHCONTEXT_DATA_DIR` | `~/.jhcontext-crewai` | Override data directory for Chalice local mode |
| `JHCONTEXT_API_URL` | `http://localhost:8400` | API URL for the agent (set automatically by `--local`) |

### Which Mode to Use?

| Goal | Mode | Command |
|------|------|---------|
| **Run agent scenarios** | `--local` flag | `python -m agent.run --local --scenario healthcare` |
| **Debug API routes** | Chalice local | `JHCONTEXT_LOCAL=1 chalice local --port 8400` |
| **Full-stack debugging** | Two terminals | Chalice local + agent in separate terminals |
| **Deploy to AWS** | `chalice deploy` | `cd api && chalice deploy` (uses DynamoDB) |

## License

Apache 2.0

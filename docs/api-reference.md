# API Reference

After deploying, replace `$API` with your endpoint URL:

```bash
API=https://{api-id}.execute-api.us-east-1.amazonaws.com/api
```

## Health Check

```bash
curl $API/health
# {"status": "ok", "service": "jhcontext-api", "version": "0.2.0"}
```

## Envelopes

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

## Artifacts

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

## Provenance

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

## Decisions

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

## Compliance

### Export compliance package (ZIP)

```bash
curl $API/compliance/package/ctx-test-001 -o compliance.zip
# Downloads ZIP containing: envelope.json, provenance.ttl, audit_report.json, manifest.json
```

## MCP Endpoint

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

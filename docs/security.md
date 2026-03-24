# Securing the API and MCP

The current deployment is **open** (no authentication) — appropriate for a research
prototype. Below is the security roadmap for production hardening.

## Phase 1: API Key Authentication (Immediate)

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

## Phase 2: IAM Authorization (Recommended for AWS-native)

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

## Phase 3: Cognito JWT (If Multi-Tenant)

If multiple agents or tenants need separate access:

```python
# Same pattern as vendia-api — Chalice built-in JWT authorizer
@app.route("/envelopes", methods=["POST"], cors=True,
           authorizer=CognitoUserPoolAuthorizer("JHContextPool",
               provider_arns=["arn:aws:cognito-idp:..."],
               header="Authorization"))
```

## Phase 4: mTLS (For Paper / Compliance)

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

## MCP-Specific Security

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

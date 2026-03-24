# Local Development (Without AWS)

The entire project runs locally without AWS credentials, DynamoDB, S3, or Lambda.
The agent communicates via HTTP — it doesn't care whether the backend is DynamoDB or
SQLite. All you need is a local server.

## Quick Start (Single Command)

```bash
cd jhcontext-crewai
python -m agent.run --local --scenario healthcare
```

This auto-starts a local server (SQLite backend), runs the scenario, saves outputs
to `output/`, and shuts down the server when done. No second terminal needed.

## How It Works

```
LOCAL MODE (--local):
┌──────────────────────────────────────────────┐
│ Local Server (auto-started subprocess)       │
│  SQLiteStorage → ~/.jhcontext-crewai/data.db │
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

## Local Modes

### 1. `--local` flag (recommended for agent development)

```bash
python -m agent.run --local --scenario healthcare
python -m agent.run --local --scenario all
python -m agent.run --local --scenario all && python -m agent.run --validate
```

The `--local` flag:
1. Tries `chalice local` first (if Chalice is installed) — uses the actual Chalice API routes with SQLite
2. Falls back to the SDK's FastAPI server (via `uvicorn`) — same routes, same interface
3. Polls `/health` until ready, runs your scenarios, terminates on exit

### 2. `JHCONTEXT_LOCAL=1 chalice local` (for API development)

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

### 3. SDK server (manual, two terminals)

```bash
# Terminal 1:
cd ~/Repos/jhcontext-sdk
uvicorn jhcontext.server.app:create_app --factory --port 8400

# Terminal 2:
cd ~/Repos/jhcontext-crewai
export JHCONTEXT_API_URL=http://localhost:8400
python -m agent.run --scenario healthcare
```

## Storage Backends

| Mode | Envelopes | PII Vault | Artifacts | Config |
|------|-----------|-----------|-----------|--------|
| **AWS** (deployed) | DynamoDB | DynamoDB (separate table) | S3 | `.chalice/config.json` env vars |
| **Chalice local** | SQLite `~/.jhcontext-crewai/data.db` | SQLite `pii_vault.db` | Filesystem `~/.jhcontext-crewai/artifacts/` | `JHCONTEXT_LOCAL=1` |
| **SDK server** | SQLite `~/.jhcontext/data.db` | SQLite `pii_vault.db` | Filesystem `~/.jhcontext/artifacts/` | SDK defaults |

Both SQLite backends implement the **exact same StorageBackend protocol** as DynamoDB —
same 9 methods, same semantics, same return types.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JHCONTEXT_LOCAL` | _(unset)_ | Set to `1` to switch Chalice API to SQLite backend |
| `JHCONTEXT_DATA_DIR` | `~/.jhcontext-crewai` | Override data directory for Chalice local mode |
| `JHCONTEXT_API_URL` | `http://localhost:8400` | API URL for the agent (set automatically by `--local`) |

## Which Mode to Use?

| Goal | Mode | Command |
|------|------|---------|
| **Run agent scenarios** | `--local` flag | `python -m agent.run --local --scenario healthcare` |
| **Debug API routes** | Chalice local | `JHCONTEXT_LOCAL=1 chalice local --port 8400` |
| **Full-stack debugging** | Two terminals | Chalice local + agent in separate terminals |
| **Deploy to AWS** | `chalice deploy` | `cd api && chalice deploy` (uses DynamoDB) |

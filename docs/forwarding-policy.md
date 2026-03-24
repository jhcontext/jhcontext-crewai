# Forwarding Policy

The protocol supports two deployment patterns for inter-task data flow, controlled by
`compliance.forwarding_policy` in each task's envelope output.

## Policy Types

| Policy | Description | Risk Level |
|--------|-------------|------------|
| `semantic_forward` | Next task receives **only** `semantic_payload` — structured, auditable semantic extractions. Raw tokens/vectors/embeddings are stripped from the context before the next task runs. | Required for HIGH |
| `raw_forward` | Next task receives the full envelope (all fields). Faster, but audit trail may diverge from what the agent actually consumed. | Permitted for LOW/MEDIUM |

## Key Properties

- **Per-task granularity** — each task controls its own forwarding via the envelope it
  outputs. A fetch task can use `raw_forward` while the downstream classification task
  switches to `semantic_forward`.

- **Monotonic enforcement** — once any task in a crew sets `semantic_forward`, subsequent
  tasks **cannot downgrade** to `raw_forward`. The `ContextMixin._resolve_forwarding_policy()`
  tracks this boundary in flow state. Violations are overridden with a logged warning.

- **Full persistence regardless** — the callback persists the **complete envelope** (with
  all artifact metadata) to the backend API, even when the next task only sees
  `semantic_payload`. Nothing is lost for audit — raw artifacts are always in the backend
  for debugging.

- **Envelope-driven** — the `forwarding_policy` is a first-class field in the
  `ComplianceBlock`, not a prompt instruction. The `EnvelopeBuilder.set_risk_level(HIGH)`
  auto-sets `semantic_forward`; `set_risk_level(LOW)` auto-sets `raw_forward`. Tasks can
  override via their YAML-instructed envelope output.

## Healthcare Example (Mixed Forwarding)

```
sensor_task  (raw_forward)      →  output.raw = full envelope (all observations)
                                        ↓  situation_task sees everything
situation_task (semantic_forward) →  output.raw = {"semantic_payload": [...]} ONLY
                                        ↓  decision_task sees only semantic data
decision_task (semantic_forward)  →  only semantic_payload visible
```

The **semantic boundary** is at the classification step (situation_task). Before it, raw
data flows freely for ingestion. After it, only structured semantic extractions are
visible to decision-making tasks — enforced structurally, not by prompt.

## Recommendation Example (Raw-Forward Throughout)

```
profile_task  (raw_forward)  →  search_agent sees EVERYTHING
search_task   (raw_forward)  →  personalize_agent sees EVERYTHING
```

No semantic boundary. All agents consume full aggregated context.

## Task Preamble Injection

The `ContextMixin._get_forwarding_preamble()` method generates a constraint instruction
from the flow-level envelope's forwarding policy. This preamble is passed to
`crew.kickoff(inputs=...)` and interpolated into task descriptions via
`{_forwarding_preamble}` placeholders in YAML. For Semantic-Forward flows, tasks receive
an explicit instruction to read only `semantic_payload`. For Raw-Forward, the preamble is
empty.

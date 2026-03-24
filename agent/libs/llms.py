"""LLM configuration for jhcontext-aws agent crews.

Same model selection pattern as vendia-agent/src/libs/llms.py:
- Claude Sonnet → complex reasoning, content generation (default)
- Claude Haiku  → classification, data extraction, fast structured output

Uses direct LLM instantiation (no lazy wrapper needed since the agent
runs locally, not in Lambda where env vars may be unavailable at import).
"""

import os

from crewai import LLM

_anthropic_key = os.getenv("ANTHROPIC_API_KEY")

# ── Model IDs ────────────────────────────────────────────────────

claude_sonnet = "anthropic/claude-sonnet-4-6"
claude_haiku = "anthropic/claude-haiku-4-5-20251001"

# ── Sonnet instances (default for reasoning + content) ───────────

# High-capability reasoning: strategic planning, audit, oversight
llm_manager_claude = LLM(
    model=claude_sonnet, temperature=0.1,
    api_key=_anthropic_key, max_retries=5,
)

# Creative content: treatment recommendations, narrative reports
llm_content_claude = LLM(
    model=claude_sonnet, temperature=0.7,
    api_key=_anthropic_key, max_retries=5,
)

# ── Haiku instances (classification + data extraction) ───────────

# Efficient data processing: sensor data, structured extraction
llm_data_claude = LLM(
    model=claude_haiku, temperature=0.0,
    api_key=_anthropic_key, max_retries=5,
)

# Classification: routing, grading rubric scoring, risk assessment
llm_classifier_claude = LLM(
    model=claude_haiku, temperature=0.0,
    api_key=_anthropic_key, max_retries=5,
)

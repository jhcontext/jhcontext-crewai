"""Benefits A3I crew — AI Auditor Assistant for citizen-facing benefits chatbot.

Demonstrates PAC-AI Semantic-Forward vs Raw-Forward as two pipelines on the
same input, with the resulting envelopes' PROV + semantic_payload queryable
via four SPARQL templates (see queries/).

Anchored on the Dutch toeslagenaffaire-style scenario: a citizen asks the A3I
"why was my benefits claim reduced?". The A3I orchestrates a multi-turn agentic
session (intake → semantic extractor → decision agent), produces an answer with
cited sources, and emits PAC-AI envelopes whose semantic_payload is auditable
by the citizen post-hoc.
"""

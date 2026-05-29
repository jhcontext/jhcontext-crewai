"""Benefits A3I (AI Auditor Assistant) Flow — citizen-facing benefits chatbot.

Demonstrates PAC-AI Semantic-Forward vs Raw-Forward as two pipelines on the
same input. The Flow runs the same BenefitsA3ICrew twice with different
forwarding-policy preambles, then makes both envelope chains available for
the citizen SPARQL queries (see agent/scenarios/benefits_a3i/citizen_query.py).

Anchored on the Dutch toeslagenaffaire-style scenario: a citizen asks the
A3I "why was my benefits claim reduced?". The A3I orchestrates a multi-turn
agentic session and emits PAC-AI envelopes that the citizen can later audit
via SPARQL.

For deterministic offline verification (no LLM key needed), use the simulate
runner at agent/scenarios/benefits_a3i/simulate.py — it builds the same
envelopes via lib.benefits_eligibility_statement and feeds an equivalent
PROV graph to the four citizen SPARQL queries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.benefits_a3i.crew import BenefitsA3ICrew
from agent.protocol.context_mixin import ContextMixin

from jhcontext import ForwardingPolicy, RiskLevel

import agent.output_dir as _out


class BenefitsA3IFlow(Flow, ContextMixin):
    """Benefits-help A3I flow with two pipelines on the same citizen case.

    Pipeline 1 (raw_forward): baseline — limits the citizen's audit to
    the artifact-pointer level (the integrity SPARQL query).
    Pipeline 2 (semantic_forward): full — the citizen can additionally run
    semantic-claim, reasoning-chain, and counterfactual SPARQL queries
    over the resulting envelopes' interpretation- and situation-layer
    statements in the PROV graph.
    """

    @start()
    def init(self):
        _out.current.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="benefits.eligibility_explanation",
            producer="did:gov:a3i-system",
            risk_level=RiskLevel.HIGH,
            human_oversight=True,
        )

        self._register_crew(
            crew_id="crew:benefits-a3i",
            label="A3I Benefits Pipeline",
            agent_ids=[
                "did:gov:a3i-intake-agent",
                "did:gov:a3i-semantic-extractor",
                "did:gov:a3i-decision-agent",
            ],
        )

        print(f"[Benefits A3I] Initialized context: {context_id}")
        return self.state.get("citizen_input", self._default_citizen_case())

    @listen(init)
    def raw_forward_pipeline(self, input_data):
        """Pipeline 1: raw_forward baseline.

        The decision agent receives upstream artefacts directly; the citizen
        can later run the integrity SPARQL query (artifact-pointer level),
        but the semantic-claim / reasoning-chain / counterfactual queries
        return empty because no interpretation-layer statements were emitted.
        """
        print("[Benefits A3I] Pipeline 1/2: Raw-Forward...")

        crew_instance = BenefitsA3ICrew().crew()
        crew_instance.task_callback = self._persist_task_callback

        # Override forwarding-policy preamble for this run
        raw_preamble = ForwardingPolicy.RAW_FORWARD.format_preamble(risk_level="high")

        result = crew_instance.kickoff(inputs={
            **input_data,
            "_forwarding_preamble": raw_preamble,
        })
        return result.raw

    @listen(raw_forward_pipeline)
    def semantic_forward_pipeline(self, _raw_output):
        """Pipeline 2: semantic_forward (this is the citizen-rights pipeline).

        Each task emits a full UserML SituationReport; the decision agent
        monotonically consumes the upstream extractor's interpretation and
        situation statements. The resulting PROV graph carries the per-
        statement triples that the semantic-claim / reasoning-chain /
        counterfactual SPARQL queries traverse.
        """
        print("[Benefits A3I] Pipeline 2/2: Semantic-Forward...")

        crew_instance = BenefitsA3ICrew().crew()
        crew_instance.task_callback = self._persist_task_callback

        semantic_preamble = ForwardingPolicy.SEMANTIC_FORWARD.format_preamble(
            risk_level="high"
        )

        result = crew_instance.kickoff(inputs={
            **self.state.get("citizen_input", self._default_citizen_case()),
            "_forwarding_preamble": semantic_preamble,
        })

        # Save outputs for the citizen_query runner
        self._save_outputs(result.raw)
        return result.raw

    def _save_outputs(self, decision_output: str):
        """Persist envelopes + PROV graph for the citizen_query SPARQL runner."""
        context_id = self.state["_context_id"]

        task_envelopes = self.state.get("_task_envelopes", [])
        (_out.current / "benefits_a3i_envelopes.json").write_text(
            json.dumps(task_envelopes, indent=2)
        )

        prov_turtle = self.state["_prov"].serialize("turtle")
        (_out.current / "benefits_a3i_prov.ttl").write_text(prov_turtle)

        summary = {
            "context_id": context_id,
            "scope": "benefits.eligibility_explanation",
            "pipelines_run": ["raw_forward", "semantic_forward"],
            "final_decision_preview": decision_output[:300],
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        (_out.current / "benefits_a3i_summary.json").write_text(
            json.dumps(summary, indent=2)
        )

        metrics = self._finalize_metrics()
        (_out.current / "benefits_a3i_metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )

        self._cleanup()
        print(f"[Benefits A3I] Outputs saved to {_out.current}/")
        print(
            "[Benefits A3I] Run: python -m agent.scenarios.benefits_a3i.citizen_query"
        )

    @staticmethod
    def _default_citizen_case() -> dict:
        """Default toeslagenaffaire-style case: tier-2 ineligible by EUR 7000."""
        return {
            "citizen_question": "Why was my benefits claim reduced?",
            "claim_id": "claim-tslg-2024-04217",
            "citizen_id": "cit-anonym-9b3f",
            "income_eur": 42000,
            "current_tier": "tier_1",
            "requested_tier": "tier_2",
            "year": 2024,
        }

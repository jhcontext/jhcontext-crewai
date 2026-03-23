"""Product Recommendation Flow — LOW-risk Raw-Forward scenario.

2-step pipeline: init → recommend.

Demonstrates Raw-Forward task chaining: a single RecommendationCrew
with 3 tasks (profile → search → personalize) where agents consume raw
aggregated context rather than reading from ``semantic_payload``.

No separate oversight or audit crews — LOW-risk under EU AI Act does not
require mandatory human oversight. Protocol persistence still records
full envelopes + PROV for traceability.
"""

from __future__ import annotations

import json
from pathlib import Path

from crewai.flow.flow import Flow, listen, start

from agent.crews.recommendation.crew import RecommendationCrew
from agent.protocol.context_mixin import ContextMixin

from jhcontext import RiskLevel

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


class RecommendationFlow(Flow, ContextMixin):
    """Product recommendation flow (LOW-risk, Raw-Forward).

    Demonstrates that LOW-risk scenarios can use Raw-Forward task
    chaining — agents consume raw output tokens for speed, without
    the Semantic-Forward constraint of reading only from
    ``semantic_payload``. Protocol persistence still happens via
    task callbacks for full auditability.
    """

    @start()
    def init(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        context_id = self._init_context(
            scope="product_recommendation",
            producer="did:ecommerce:rec-system",
            risk_level=RiskLevel.LOW,
            human_oversight=False,
        )
        print(f"[Recommendation] Initialized context: {context_id}")
        return self.state.get("user_input", self._default_user())

    @listen(init)
    def recommend(self, input_data):
        """Single crew, 3 tasks, Raw-Forward context passing."""
        print("[Recommendation] Running recommendation pipeline (Raw-Forward)...")

        rec_crew = RecommendationCrew()
        crew_instance = rec_crew.crew()
        crew_instance.task_callback = self._persist_task_callback

        preamble = self.state["_forwarding_preamble"]
        result = crew_instance.kickoff(inputs={
            **input_data,
            "_forwarding_preamble": preamble,
        })

        # Log the recommendation decision
        self._log_decision(
            outcome={"recommendations": result.raw[:300]},
            agent_id="did:ecommerce:personalize-agent",
        )

        # Save outputs
        self._save_outputs(result.raw)
        return result.raw

    def _save_outputs(self, recommendation_output: str):
        """Save envelope, PROV, recommendation output, and metrics."""
        context_id = self.state["_context_id"]
        client = self.state["_api_client"]

        # Envelope
        envelope = client.get_envelope(context_id)
        (OUTPUT_DIR / "recommendation_envelope.json").write_text(
            json.dumps(envelope, indent=2)
        )

        # PROV graph
        prov_turtle = self.state["_prov"].serialize("turtle")
        (OUTPUT_DIR / "recommendation_prov.ttl").write_text(prov_turtle)

        # Recommendation output
        (OUTPUT_DIR / "recommendation_output.json").write_text(
            json.dumps(
                {"context_id": context_id, "recommendations": recommendation_output},
                indent=2,
            )
        )

        # Metrics
        metrics = self._finalize_metrics()
        (OUTPUT_DIR / "recommendation_metrics.json").write_text(
            json.dumps(metrics, indent=2)
        )

        self._cleanup()
        print(f"[Recommendation] Outputs saved to {OUTPUT_DIR}/")

    @staticmethod
    def _default_user() -> dict:
        return {
            "user_id": "U-98765",
            "browsing_history": (
                "Running shoes (Nike, Adidas), wireless headphones, "
                "yoga mats, protein powder, fitness trackers"
            ),
            "purchase_history": (
                "Nike Air Zoom Pegasus 40 ($120), Bose QuietComfort 45 ($280), "
                "Manduka PRO yoga mat ($120), Garmin Venu 3 ($450)"
            ),
        }

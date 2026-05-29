"""Live runner for the Benefits A3I scenario (requires LLM credentials).

Kicks off BenefitsA3IFlow with the default toeslagenaffaire-style case and
saves envelopes + PROV graph to the current output directory. After running
this, use `python -m agent.scenarios.benefits_a3i.citizen_query` to exercise
the four citizen SPARQL queries against the produced graph.

Use `python -m agent.scenarios.benefits_a3i.simulate` if you want an
LLM-free deterministic version (recommended for fast verification + tests).
"""

from __future__ import annotations

from agent.flows.benefits_a3i_flow import BenefitsA3IFlow


def main() -> None:
    flow = BenefitsA3IFlow()
    flow.kickoff()


if __name__ == "__main__":
    main()

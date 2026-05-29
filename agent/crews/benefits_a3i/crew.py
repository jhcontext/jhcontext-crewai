"""Benefits A3I crew — three-agent pipeline (intake → semantic extractor → decision).

The same crew supports both Raw-Forward and Semantic-Forward modes; the
difference is in the ``_forwarding_preamble`` injected at task description
substitution time (the Flow layer controls this — see ``benefits_a3i_flow.py``).

In Raw-Forward mode the decision agent gets the upstream artefacts directly
(useful as a baseline that limits what citizens can audit afterwards). In
Semantic-Forward mode the decision agent must consume the upstream
``semantic_payload`` only — and the citizen can run SPARQL queries over the
resulting interpretation- and situation-layer statements in the PROV graph.
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from jhcontext.flat_envelope import FlatEnvelope

from agent.libs.llms import (
    llm_classifier_claude,
    llm_content_claude,
    llm_data_claude,
)


@CrewBase
class BenefitsA3ICrew:
    """A3I benefits-help pipeline: 3 agents, 3 tasks, FlatEnvelope output."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def intake_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["intake_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — structured data extraction
        )

    @agent
    def semantic_extractor(self) -> Agent:
        return Agent(
            config=self.agents_config["semantic_extractor"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — rule-based classification
        )

    @agent
    def decision_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["decision_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — citizen-readable explanation
        )

    @task
    def intake_task(self) -> Task:
        return Task(
            config=self.tasks_config["intake_task"],
            output_pydantic=FlatEnvelope,
        )

    @task
    def extractor_task(self) -> Task:
        return Task(
            config=self.tasks_config["extractor_task"],
            context=[self.intake_task()],
            output_pydantic=FlatEnvelope,
        )

    @task
    def decision_task(self) -> Task:
        return Task(
            config=self.tasks_config["decision_task"],
            context=[self.extractor_task()],
            output_pydantic=FlatEnvelope,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )

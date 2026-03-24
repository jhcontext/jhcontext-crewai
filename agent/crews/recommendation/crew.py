"""Product recommendation crew — LOW-risk Raw-Forward scenario.

Single crew with 3 agents and 3 tasks demonstrating Raw-Forward task
chaining: agents consume raw aggregated context (CrewAI default) rather
than reading specifically from ``semantic_payload``. Each task still
outputs a full jhcontext Envelope for protocol persistence via callback.
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
class RecommendationCrew:
    """Product recommendation: profile → search → personalize (Raw-Forward)."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def profile_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["profile_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — user data extraction
        )

    @agent
    def search_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["search_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — product matching/classification
        )

    @agent
    def personalize_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["personalize_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — creative recommendation writing
        )

    @task
    def profile_task(self) -> Task:
        return Task(
            config=self.tasks_config["profile_task"],
            output_pydantic=FlatEnvelope,
        )

    @task
    def search_task(self) -> Task:
        return Task(
            config=self.tasks_config["search_task"],
            output_pydantic=FlatEnvelope,
        )

    @task
    def personalize_task(self) -> Task:
        return Task(
            config=self.tasks_config["personalize_task"],
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

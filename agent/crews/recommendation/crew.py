"""Product recommendation crew — LOW-risk Raw-Forward scenario.

Single crew with 3 agents and 3 tasks demonstrating Raw-Forward task
chaining: agents consume raw aggregated context (CrewAI default) rather
than reading specifically from ``semantic_payload``. Each task still
outputs a full jhcontext Envelope for protocol persistence via callback.
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from jhcontext.models import Envelope


@CrewBase
class RecommendationCrew:
    """Product recommendation: profile → search → personalize (Raw-Forward).

    Unlike the healthcare Semantic-Forward crew, tasks here do NOT use
    explicit ``context=[...]``. CrewAI's default sequential process
    aggregates all previous raw outputs — agents read the full context
    string, not a specific envelope field. This is the Raw-Forward
    pattern: faster, permitted for LOW-risk scenarios.
    """

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def profile_agent(self) -> Agent:
        return Agent(config=self.agents_config["profile_agent"], verbose=True)

    @agent
    def search_agent(self) -> Agent:
        return Agent(config=self.agents_config["search_agent"], verbose=True)

    @agent
    def personalize_agent(self) -> Agent:
        return Agent(config=self.agents_config["personalize_agent"], verbose=True)

    @task
    def profile_task(self) -> Task:
        return Task(
            config=self.tasks_config["profile_task"],
            output_pydantic=Envelope,
        )

    @task
    def search_task(self) -> Task:
        return Task(
            config=self.tasks_config["search_task"],
            output_pydantic=Envelope,
        )

    @task
    def personalize_task(self) -> Task:
        return Task(
            config=self.tasks_config["personalize_task"],
            output_pydantic=Envelope,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )

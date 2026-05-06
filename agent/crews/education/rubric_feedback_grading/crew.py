"""Rubric-grounded education crews — three scenarios on a shared 6-agent pipeline.

Auditable AI assessment: provenance-aware evaluation and rubric-grounded
feedback for student work (three scenarios, A/B/C).

Crews:
  - RubricIngestionCrew         — Stage 1 (ingestion)
  - RubricCriterionScoringCrew  — Stage 2 (per-criterion scoring)
  - RubricFeedbackCrew          — Stage 3 (per-sentence feedback w/ bindings)
  - RubricEquityCrew            — isolated equity workflow (Scenario A)
  - RubricTAReviewCrew          — human oversight (Scenario C)
  - RubricAuditCrew             — combined narrative audit (A+B+C)
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from jhcontext.flat_envelope import FlatEnvelope

from agent.libs.llms import (
    llm_classifier_claude,
    llm_content_claude,
    llm_data_claude,
    llm_manager_claude,
)


@CrewBase
class RubricIngestionCrew:
    """Stage 1 — essay ingestion and identity separation."""

    agents_config = "config/ingestion_agents.yaml"
    tasks_config = "config/ingestion_tasks.yaml"

    @agent
    def ingestion_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["ingestion_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — structured data separation
        )

    @task
    def ingestion_task(self) -> Task:
        return Task(
            config=self.tasks_config["ingestion_task"],
            output_pydantic=FlatEnvelope,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class RubricCriterionScoringCrew:
    """Stage 2 — per-criterion scoring with confidence and evidence-span hints."""

    agents_config = "config/criterion_scoring_agents.yaml"
    tasks_config = "config/criterion_scoring_tasks.yaml"

    @agent
    def criterion_scoring_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["criterion_scoring_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — rubric classification
        )

    @task
    def criterion_scoring_task(self) -> Task:
        return Task(
            config=self.tasks_config["criterion_scoring_task"],
            output_pydantic=FlatEnvelope,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class RubricFeedbackCrew:
    """Stage 3 — per-sentence feedback with rubric-criterion binding."""

    agents_config = "config/feedback_agents.yaml"
    tasks_config = "config/feedback_tasks.yaml"

    @agent
    def feedback_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["feedback_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — content generation with structured output
        )

    @task
    def feedback_task(self) -> Task:
        return Task(
            config=self.tasks_config["feedback_task"],
            output_pydantic=FlatEnvelope,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class RubricEquityCrew:
    """Isolated equity reporting workflow (Scenario A — workflow isolation).

    Self-contained within the ``rubric_feedback_grading`` subpackage so that
    a reviewer opening the folder sees every crew the three scenarios
    exercise; this mirrors the ``fair_grading`` equity crew with variant-
    specific wording.
    """

    agents_config = "config/equity_agents.yaml"
    tasks_config = "config/equity_tasks.yaml"

    @agent
    def equity_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["equity_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — aggregate data processing
        )

    @task
    def equity_task(self) -> Task:
        return Task(config=self.tasks_config["equity_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class RubricTAReviewCrew:
    """Scenario C — teaching-assistant review with structured oversight narrative."""

    agents_config = "config/ta_review_agents.yaml"
    tasks_config = "config/ta_review_tasks.yaml"

    @agent
    def ta_review_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["ta_review_agent"],
            verbose=True,
            llm=llm_manager_claude,  # Sonnet — reasoning about AI output
        )

    @task
    def ta_review_task(self) -> Task:
        return Task(config=self.tasks_config["ta_review_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class RubricAuditCrew:
    """Combined A+B+C narrative audit, fed by the SDK verifiers' machine output."""

    agents_config = "config/audit_agents.yaml"
    tasks_config = "config/audit_tasks.yaml"

    @agent
    def audit_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["audit_agent"],
            verbose=True,
            llm=llm_manager_claude,  # Sonnet — compliance reasoning
        )

    @task
    def audit_task(self) -> Task:
        return Task(config=self.tasks_config["audit_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)

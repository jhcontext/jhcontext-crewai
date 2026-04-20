"""Rubric-grounded oral grading crews — three scenarios on a shared 6-agent pipeline.

Multimodal extension of ``rubric_feedback_grading``: the input is a
student audio submission; the feedback agent binds each sentence to an
(start_ms, end_ms) window on the source recording. A modality-aware
verifier (``verify_multimodal_binding``, SDK) checks the span shape.

Crews:
  - OralAudioIngestionCrew      — Stage 1 (audio ingestion + STT alignment)
  - OralCriterionScoringCrew    — Stage 2 (per-criterion scoring w/ window hints)
  - OralFeedbackCrew            — Stage 3 (per-sentence feedback w/ audio windows)
  - OralEquityCrew              — isolated equity workflow (Scenario A)
  - OralTAReviewCrew            — human oversight (Scenario C)
  - OralAuditCrew               — combined narrative audit (A+B-multimodal+C)
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from agent.libs.llms import (
    llm_classifier_claude,
    llm_content_claude,
    llm_data_claude,
    llm_manager_claude,
)


@CrewBase
class OralAudioIngestionCrew:
    """Stage 1 — audio ingestion, identity separation, STT + alignment."""

    agents_config = "config/audio_ingestion_agents.yaml"
    tasks_config = "config/audio_ingestion_tasks.yaml"

    @agent
    def audio_ingestion_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["audio_ingestion_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — structured data separation
        )

    @task
    def audio_ingestion_task(self) -> Task:
        return Task(config=self.tasks_config["audio_ingestion_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class OralCriterionScoringCrew:
    """Stage 2 — per-criterion scoring with window-hint evidence on the audio."""

    agents_config = "config/oral_criterion_scoring_agents.yaml"
    tasks_config = "config/oral_criterion_scoring_tasks.yaml"

    @agent
    def oral_criterion_scoring_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["oral_criterion_scoring_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — rubric classification
        )

    @task
    def oral_criterion_scoring_task(self) -> Task:
        return Task(config=self.tasks_config["oral_criterion_scoring_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class OralFeedbackCrew:
    """Stage 3 — per-sentence feedback with modality-aware binding."""

    agents_config = "config/oral_feedback_agents.yaml"
    tasks_config = "config/oral_feedback_tasks.yaml"

    @agent
    def oral_feedback_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["oral_feedback_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — content generation with structured output
        )

    @task
    def oral_feedback_task(self) -> Task:
        return Task(config=self.tasks_config["oral_feedback_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class OralEquityCrew:
    """Isolated equity reporting workflow for oral assessments.

    Self-contained within the ``oral_feedback_grading`` subpackage so that
    a reviewer opening the folder sees every crew the three oral
    scenarios exercise; mirrors the ``rubric_feedback_grading`` equity
    crew with oral-specific wording.
    """

    agents_config = "config/equity_agents.yaml"
    tasks_config = "config/equity_tasks.yaml"

    @agent
    def equity_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["equity_agent"],
            verbose=True,
            llm=llm_data_claude,
        )

    @task
    def equity_task(self) -> Task:
        return Task(config=self.tasks_config["equity_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class OralTAReviewCrew:
    """Scenario C (oral) — TA review with structured oversight narrative.

    TA listens to the cited audio windows (not just reads a transcript),
    so the review activity has extra document-open events for the audio
    artifact itself alongside the usual rubric + AI-score + AI-feedback.
    """

    agents_config = "config/oral_ta_review_agents.yaml"
    tasks_config = "config/oral_ta_review_tasks.yaml"

    @agent
    def oral_ta_review_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["oral_ta_review_agent"],
            verbose=True,
            llm=llm_manager_claude,  # Sonnet — reasoning about AI output
        )

    @task
    def oral_ta_review_task(self) -> Task:
        return Task(config=self.tasks_config["oral_ta_review_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class OralAuditCrew:
    """Combined A+B(multimodal)+C narrative audit, fed by the SDK verifiers'
    machine output."""

    agents_config = "config/audit_agents.yaml"
    tasks_config = "config/audit_tasks.yaml"

    @agent
    def audit_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["audit_agent"],
            verbose=True,
            llm=llm_manager_claude,
        )

    @task
    def audit_task(self) -> Task:
        return Task(config=self.tasks_config["audit_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)

"""Healthcare compliance crews — Article 14 human oversight.

HealthcareClinicalCrew: multi-task crew (sensor → situation → decision)
demonstrating Semantic-Forward task chaining with full Envelope output.

HealthcareOversightCrew / HealthcareAuditCrew: single-task crews kept
separate for regulatory isolation (physician oversight and audit must
be independent of the clinical AI pipeline).
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
class HealthcareClinicalCrew:
    """Clinical pipeline: sensor → situation → decision (3 agents, 3 tasks)."""

    agents_config = "config/clinical_agents.yaml"
    tasks_config = "config/clinical_tasks.yaml"

    @agent
    def sensor_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["sensor_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — structured data extraction
        )

    @agent
    def situation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["situation_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — clinical classification
        )

    @agent
    def decision_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["decision_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — complex treatment reasoning
        )

    @task
    def sensor_task(self) -> Task:
        return Task(
            config=self.tasks_config["sensor_task"],
            output_pydantic=FlatEnvelope,
        )

    @task
    def situation_task(self) -> Task:
        return Task(
            config=self.tasks_config["situation_task"],
            context=[self.sensor_task()],
            output_pydantic=FlatEnvelope,
        )

    @task
    def decision_task(self) -> Task:
        return Task(
            config=self.tasks_config["decision_task"],
            context=[self.situation_task()],
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


@CrewBase
class HealthcareOversightCrew:
    """Physician oversight simulation crew."""

    agents_config = "config/oversight_agents.yaml"
    tasks_config = "config/oversight_tasks.yaml"

    @agent
    def oversight_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["oversight_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — clinical judgment narrative
        )

    @task
    def oversight_task(self) -> Task:
        return Task(config=self.tasks_config["oversight_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class HealthcareAuditCrew:
    """Compliance audit crew."""

    agents_config = "config/audit_agents.yaml"
    tasks_config = "config/audit_tasks.yaml"

    @agent
    def audit_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["audit_agent"],
            verbose=True,
            llm=llm_manager_claude,  # Sonnet — strategic audit reasoning
        )

    @task
    def audit_task(self) -> Task:
        return Task(config=self.tasks_config["audit_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)

"""Healthcare compliance crews — Article 14 human oversight.

The cardiac-triage clinical workflow is two *composed* pipelines (PAC-AI
mixed-mode): a raw_forward pipeline whose terminal artifact feeds a
semantic_forward pipeline.

- HealthcareRawCrew      : sensor → ontology_classification (raw_forward).
  Reads the raw signal and classifies it against a clinical ontology
  (SNOMED/LOINC); the full envelope crosses the internal handoff.
- HealthcareSemanticCrew : triage → allocation (semantic_forward).
  Consumes only the upstream ontology-classified semantic_payload; each
  handoff is filtered to the semantic_payload.

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
class HealthcareRawCrew:
    """raw_forward pipeline: sensor → ontology_classification (2 agents, 2 tasks)."""

    agents_config = "config/raw_agents.yaml"
    tasks_config = "config/raw_tasks.yaml"

    @agent
    def sensor_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["sensor_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — raw data extraction
        )

    @agent
    def ontology_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["ontology_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — ontology classification
        )

    @task
    def sensor_task(self) -> Task:
        return Task(
            config=self.tasks_config["sensor_task"],
            output_pydantic=FlatEnvelope,
        )

    @task
    def ontology_classification_task(self) -> Task:
        return Task(
            config=self.tasks_config["ontology_classification_task"],
            context=[self.sensor_task()],
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
class HealthcareSemanticCrew:
    """semantic_forward pipeline: triage → allocation (2 agents, 2 tasks).

    Consumes the raw pipeline's terminal artifact (the ontology-classified
    semantic_payload) via the ``upstream_semantic_payload`` input.
    """

    agents_config = "config/semantic_agents.yaml"
    tasks_config = "config/semantic_tasks.yaml"

    @agent
    def triage_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["triage_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — triage classification
        )

    @agent
    def allocation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["allocation_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — allocation reasoning
        )

    @task
    def triage_task(self) -> Task:
        return Task(
            config=self.tasks_config["triage_task"],
            output_pydantic=FlatEnvelope,
        )

    @task
    def allocation_task(self) -> Task:
        return Task(
            config=self.tasks_config["allocation_task"],
            context=[self.triage_task()],
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

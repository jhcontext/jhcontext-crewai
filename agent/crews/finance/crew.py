"""Financial credit assessment crews — EU AI Act Annex III 5(b).

FinanceCreditCrew: multi-task crew (data_collection → risk_analysis → credit_decision)
demonstrating Semantic-Forward task chaining with negative proof (Art. 13)
and explainable decision factors (GDPR Art. 22).

FinanceFairLendingCrew: isolated workflow for aggregate demographic analysis.
FinanceOversightCrew: credit officer human oversight simulation (Art. 14).
FinanceAuditCrew: composite compliance audit (all 4 patterns).
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
class FinanceCreditCrew:
    """Credit pipeline: data_collection → risk_analysis → credit_decision (3 agents, 3 tasks)."""

    agents_config = "config/credit_agents.yaml"
    tasks_config = "config/credit_tasks.yaml"

    @agent
    def data_collector_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["data_collector_agent"],
            verbose=True,
            llm=llm_data_claude,  # Haiku — structured data extraction
        )

    @agent
    def risk_analyzer_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["risk_analyzer_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — risk classification
        )

    @agent
    def decision_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["decision_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — complex decision reasoning
        )

    @task
    def data_collection_task(self) -> Task:
        return Task(
            config=self.tasks_config["data_collection_task"],
            output_pydantic=FlatEnvelope,
        )

    @task
    def risk_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config["risk_analysis_task"],
            context=[self.data_collection_task()],
            output_pydantic=FlatEnvelope,
        )

    @task
    def credit_decision_task(self) -> Task:
        return Task(
            config=self.tasks_config["credit_decision_task"],
            context=[self.risk_analysis_task()],
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
class FinanceFairLendingCrew:
    """Fair lending analysis crew — completely isolated from credit pipeline."""

    agents_config = "config/fair_lending_agents.yaml"
    tasks_config = "config/fair_lending_tasks.yaml"

    @agent
    def fair_lending_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["fair_lending_agent"],
            verbose=True,
            llm=llm_classifier_claude,  # Haiku — statistical analysis
        )

    @task
    def fair_lending_task(self) -> Task:
        return Task(config=self.tasks_config["fair_lending_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class FinanceOversightCrew:
    """Credit officer oversight simulation crew."""

    agents_config = "config/finance_oversight_agents.yaml"
    tasks_config = "config/finance_oversight_tasks.yaml"

    @agent
    def credit_officer_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["credit_officer_agent"],
            verbose=True,
            llm=llm_content_claude,  # Sonnet — judgment narrative
        )

    @task
    def oversight_task(self) -> Task:
        return Task(config=self.tasks_config["oversight_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True)


@CrewBase
class FinanceAuditCrew:
    """Compliance audit crew."""

    agents_config = "config/finance_audit_agents.yaml"
    tasks_config = "config/finance_audit_tasks.yaml"

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

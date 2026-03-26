"""Tests for domain ontologies and semantic payload validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add agent parent to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.ontologies.healthcare import (
    HEALTHCARE_PREDICATES,
    healthcare_observations,
    healthcare_payload,
    sample_healthcare,
)
from agent.ontologies.education import (
    EDUCATION_PREDICATES,
    education_observations,
    education_interpretations,
    sample_education,
)
from agent.ontologies.recommendation import (
    RECOMMENDATION_PREDICATES,
    recommendation_observations,
    sample_recommendation,
)
from agent.ontologies.finance import (
    FINANCE_PREDICATES,
    finance_observations,
    finance_interpretations,
    finance_payload,
    sample_finance,
)
from agent.ontologies.validator import validate_semantic_payload


class TestHealthcareOntology:
    def test_predicates_defined(self):
        assert "observation" in HEALTHCARE_PREDICATES
        assert "lab_result" in HEALTHCARE_PREDICATES["observation"]
        assert "risk_assessment" in HEALTHCARE_PREDICATES["interpretation"]
        assert "treatment_candidate" in HEALTHCARE_PREDICATES["situation"]

    def test_sample_healthcare_is_valid(self):
        payload = sample_healthcare()
        valid, violations = validate_semantic_payload(payload, HEALTHCARE_PREDICATES)
        assert valid, f"Violations: {violations}"

    def test_healthcare_observations(self):
        obs = healthcare_observations(
            "P-001",
            demographics={"age": 62, "gender": "M"},
            labs=[{"name": "CEA", "value": 12.5}],
            imaging=["2.3cm nodule"],
        )
        assert len(obs) == 3
        assert obs[0]["predicate"] == "demographic"
        assert obs[1]["predicate"] == "lab_result"
        assert obs[2]["predicate"] == "imaging_finding"

    def test_healthcare_payload_structure(self):
        obs = healthcare_observations("P-001", {}, [], [])
        payload = healthcare_payload("P-001", observations=obs)
        assert payload["@model"] == "UserML"
        assert "layers" in payload
        assert "observation" in payload["layers"]


class TestEducationOntology:
    def test_predicates_defined(self):
        assert "word_count" in EDUCATION_PREDICATES["observation"]
        assert "argument_quality" in EDUCATION_PREDICATES["interpretation"]
        assert "grade_assigned" in EDUCATION_PREDICATES["situation"]

    def test_sample_education_is_valid(self):
        payload = sample_education()
        valid, violations = validate_semantic_payload(payload, EDUCATION_PREDICATES)
        assert valid, f"Violations: {violations}"

    def test_education_interpretations(self):
        interps = education_interpretations(
            "essay-001",
            scores={"argument_quality": 0.82, "evidence_strength": 0.78},
        )
        assert len(interps) == 2
        assert interps[0]["confidence"] == 0.9


class TestRecommendationOntology:
    def test_predicates_defined(self):
        assert "browse_event" in RECOMMENDATION_PREDICATES["observation"]
        assert "category_affinity" in RECOMMENDATION_PREDICATES["interpretation"]
        assert "active_shopper" in RECOMMENDATION_PREDICATES["situation"]

    def test_sample_recommendation_is_valid(self):
        payload = sample_recommendation()
        valid, violations = validate_semantic_payload(payload, RECOMMENDATION_PREDICATES)
        assert valid, f"Violations: {violations}"


class TestFinanceOntology:
    def test_predicates_defined(self):
        assert "income_source" in FINANCE_PREDICATES["observation"]
        assert "employment_record" in FINANCE_PREDICATES["observation"]
        assert "debt_obligation" in FINANCE_PREDICATES["observation"]
        assert "payment_history" in FINANCE_PREDICATES["observation"]
        assert "credit_bureau_score" in FINANCE_PREDICATES["observation"]
        assert "debt_to_income_ratio" in FINANCE_PREDICATES["interpretation"]
        assert "default_probability" in FINANCE_PREDICATES["interpretation"]
        assert "creditworthy" in FINANCE_PREDICATES["situation"]
        assert "credit_decision" in FINANCE_PREDICATES["application"]
        assert "explanation_factors" in FINANCE_PREDICATES["application"]

    def test_sample_finance_is_valid(self):
        payload = sample_finance()
        valid, violations = validate_semantic_payload(payload, FINANCE_PREDICATES)
        assert valid, f"Violations: {violations}"

    def test_finance_observations(self):
        obs = finance_observations(
            "APP-001",
            income={"type": "salary", "monthly_gross": 3800},
            employment={"type": "permanent", "tenure_months": 48},
            debts=[{"type": "auto_loan", "monthly_payment": 280}],
            payments={"on_time_pct": 96},
            bureau_score=710,
        )
        assert len(obs) == 5
        assert obs[0]["predicate"] == "income_source"
        assert obs[1]["predicate"] == "employment_record"
        assert obs[2]["predicate"] == "debt_obligation"
        assert obs[3]["predicate"] == "payment_history"
        assert obs[4]["predicate"] == "credit_bureau_score"

    def test_finance_interpretations(self):
        interps = finance_interpretations(
            "APP-001",
            dti=0.32,
            payment_reliability="good",
            employment_stability="stable",
            default_prob=0.04,
        )
        assert len(interps) == 4
        assert interps[0]["predicate"] == "debt_to_income_ratio"
        assert interps[0]["object"] == 0.32

    def test_finance_payload_structure(self):
        obs = finance_observations(
            "APP-001",
            income={"type": "salary"},
            employment={"type": "permanent"},
            debts=[],
            payments={"on_time_pct": 100},
        )
        payload = finance_payload("APP-001", observations=obs)
        assert payload["@model"] == "UserML"
        assert "layers" in payload
        assert "observation" in payload["layers"]

    def test_no_protected_attributes_in_predicates(self):
        """Ensure finance ontology does not include protected attribute predicates."""
        all_predicates = []
        for layer_preds in FINANCE_PREDICATES.values():
            all_predicates.extend(layer_preds)
        protected = ["gender", "ethnicity", "marital_status", "nationality", "race", "religion", "disability"]
        for attr in protected:
            assert attr not in all_predicates, f"Protected attribute '{attr}' found in finance predicates"


class TestValidator:
    def test_valid_payload(self):
        payload = sample_healthcare()
        valid, violations = validate_semantic_payload(payload, HEALTHCARE_PREDICATES)
        assert valid
        assert violations == []

    def test_missing_model(self):
        payload = {"layers": {"observation": []}}
        valid, violations = validate_semantic_payload(payload, HEALTHCARE_PREDICATES)
        assert not valid
        assert any("@model" in v for v in violations)

    def test_invalid_predicate(self):
        payload = {
            "@model": "UserML",
            "layers": {
                "observation": [
                    {"subject": "P-001", "predicate": "invalid_predicate", "object": "foo"},
                ],
                "interpretation": [],
                "situation": [],
                "application": [],
            },
        }
        valid, violations = validate_semantic_payload(payload, HEALTHCARE_PREDICATES)
        assert not valid
        assert any("invalid_predicate" in v for v in violations)

    def test_missing_predicate_key(self):
        payload = {
            "@model": "UserML",
            "layers": {
                "observation": [
                    {"subject": "P-001", "object": "foo"},  # no predicate
                ],
                "interpretation": [],
                "situation": [],
                "application": [],
            },
        }
        valid, violations = validate_semantic_payload(payload, HEALTHCARE_PREDICATES)
        assert not valid
        assert any("missing 'predicate'" in v for v in violations)

    def test_non_dict_payload(self):
        valid, violations = validate_semantic_payload("not a dict", {})
        assert not valid

    def test_missing_layers(self):
        valid, violations = validate_semantic_payload({"@model": "UserML"}, {})
        assert not valid
        assert any("layers" in v for v in violations)

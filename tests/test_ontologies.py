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

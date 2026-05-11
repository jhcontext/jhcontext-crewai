"""Post-hoc validator for UserML semantic payloads (protocol v0.5+).

Checks that every statement in a UserML SituationReport uses a predicate
from its domain's allowed vocabulary for the matching UserML group
(Observation / Interpretation / Situation / Application). Runs after LLM
agents produce output and does NOT require SDK changes.
"""

from __future__ import annotations

from typing import Any

# UserML statement group names (administration.group) map onto the lowercase
# layer keys the domain predicate vocabularies still use.
_GROUP_TO_LAYER = {
    "Observation": "observation",
    "Interpretation": "interpretation",
    "Situation": "situation",
    "Application": "application",
}


def validate_semantic_payload(
    payload: dict[str, Any],
    domain_predicates: dict[str, list[str]],
) -> tuple[bool, list[str]]:
    """Validate a UserML SituationReport against a domain predicate vocabulary.

    Parameters
    ----------
    payload:
        SituationReport dict produced by ``jhcontext.semantics.userml_payload``
        (``@model="UserML-SituationReport"`` with a flat ``statements`` list).
    domain_predicates:
        Mapping of layer name (``observation`` / ``interpretation`` /
        ``situation`` / ``application``) → list of valid predicate strings.

    Returns
    -------
    (valid, violations):
        *valid* is True when no violations are found.
        *violations* is a list of human-readable violation descriptions.
    """
    violations: list[str] = []

    if not isinstance(payload, dict):
        return False, ["Payload is not a dict"]

    model = payload.get("@model")
    if model != "UserML-SituationReport":
        violations.append(
            f"Expected @model='UserML-SituationReport', got '{model}'"
        )

    statements = payload.get("statements")
    if not isinstance(statements, list):
        violations.append("Missing or invalid 'statements' key")
        return False, violations

    for i, stmt in enumerate(statements):
        if not isinstance(stmt, dict):
            violations.append(f"statements[{i}]: entry is not a dict")
            continue

        group = (stmt.get("administration") or {}).get("group")
        layer = _GROUP_TO_LAYER.get(group)
        if layer is None:
            # Unknown group — tolerated like extra layers were in v0.3.
            continue
        valid_predicates = domain_predicates.get(layer)
        if valid_predicates is None:
            # Domain doesn't constrain this group; skip.
            continue

        mainpart = stmt.get("mainpart") or {}
        # Situation statements hardcode mainpart.predicate='activity' (UserML
        # convention) and carry the situation type in mainpart.object; validate
        # the object instead. Every other group validates mainpart.predicate.
        if group == "Situation":
            term = mainpart.get("object")
            term_label = "mainpart.object"
        else:
            term = mainpart.get("predicate")
            term_label = "mainpart.predicate"

        if term is None:
            violations.append(
                f"statements[{i}] ({group}): missing '{term_label}'"
            )
        elif term not in valid_predicates:
            violations.append(
                f"statements[{i}] ({group}): unknown predicate '{term}' "
                f"(valid: {valid_predicates})"
            )

    return len(violations) == 0, violations

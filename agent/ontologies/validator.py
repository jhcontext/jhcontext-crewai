"""Post-hoc validator for UserML semantic payloads.

Checks that every entry in each UserML layer uses predicates from the
domain's allowed set.  Runs after LLM agents produce output — does NOT
require SDK changes.
"""

from __future__ import annotations

from typing import Any


def validate_semantic_payload(
    payload: dict[str, Any],
    domain_predicates: dict[str, list[str]],
) -> tuple[bool, list[str]]:
    """Validate a UserML payload against a domain predicate vocabulary.

    Parameters
    ----------
    payload:
        A dict with ``@model`` and ``layers`` keys (UserML format).
    domain_predicates:
        Mapping of layer name → list of valid predicate strings.

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
    if model != "UserML":
        violations.append(f"Expected @model='UserML', got '{model}'")

    layers = payload.get("layers")
    if not isinstance(layers, dict):
        violations.append("Missing or invalid 'layers' key")
        return False, violations

    for layer_name, valid_predicates in domain_predicates.items():
        entries = layers.get(layer_name, [])
        if not isinstance(entries, list):
            violations.append(f"Layer '{layer_name}' is not a list")
            continue

        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                violations.append(f"{layer_name}[{i}]: entry is not a dict")
                continue

            predicate = entry.get("predicate")
            if predicate is None:
                violations.append(f"{layer_name}[{i}]: missing 'predicate' key")
            elif predicate not in valid_predicates:
                violations.append(
                    f"{layer_name}[{i}]: unknown predicate '{predicate}' "
                    f"(valid: {valid_predicates})"
                )

    # Check for unexpected layers
    known_layers = set(domain_predicates.keys())
    for layer_name in layers:
        if layer_name not in known_layers:
            # Don't flag as violation — extra layers are tolerated
            pass

    return len(violations) == 0, violations

"""Domain ontologies for UserML semantic payloads.

Each domain module defines valid predicates per UserML layer and helper
functions that produce structured payloads using the jhcontext SDK's
``observation()``, ``interpretation()``, ``situation()``, and
``userml_payload()`` helpers.
"""

from __future__ import annotations


def inject_subject(items, default_subject: str) -> list[dict]:
    """Inject *default_subject* into each shorthand dict that lacks a subject.

    Domain ontology payloads in this repo are about a single subject
    (patient, applicant, essay, user). Per-statement shorthand dicts may
    therefore omit the ``subject`` key for brevity. This helper restores
    it before the SDK's ``userml_payload`` normalizes the shorthand.

    Pre-built UserML statements (``@model="UserML"``) and dicts that
    already carry an explicit ``subject`` pass through unchanged.
    """
    out: list[dict] = []
    for item in items or []:
        if item.get("@model") == "UserML" or "subject" in item:
            out.append(item)
        else:
            out.append({**item, "subject": default_subject})
    return out

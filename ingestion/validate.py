"""Deterministic business-rule validation on top of Pydantic contracts."""

from __future__ import annotations

import re

from ingestion.contracts import (
    ActExtractionPayload,
    ProvisionPayload,
    RulesExtractionPayload,
    parse_staging_payload,
)


def _validate_provision_text(p: ProvisionPayload) -> list[str]:
    errors: list[str] = []
    code = p.provision_code
    text = p.text_content

    if p.provision_type == "SECTION":
        has_sub = bool(re.search(r"\(\d+\)", text))
        has_clause = bool(re.search(r"\([a-z]\)", text))
        has_shall = bool(re.search(r"\bshall\b", text, re.I))
        if not has_sub and not has_clause and not has_shall and len(text) < 80:
            errors.append(
                f"{code}: section text must contain subsection (1) or substantive body"
            )

    if p.provision_type == "RULE":
        has_sub = bool(re.search(r"\(\d+\)", text))
        has_clause = bool(re.search(r"\([a-z]\)", text))
        has_shall = bool(re.search(r"\bshall\b", text, re.I))
        if not has_sub and not has_clause and not has_shall and len(text) < 80:
            errors.append(f"{code}: rule text too short and missing sub-rule (1)")

    return errors


def validate_payload(raw: dict) -> list[str]:
    """Return a list of validation errors; empty list means OK."""
    errors: list[str] = []
    try:
        payload = parse_staging_payload(raw)
    except Exception as exc:
        return [str(exc)]

    if isinstance(payload, (ActExtractionPayload, RulesExtractionPayload)):
        if not payload.provisions:
            errors.append("provisions array is empty")
        for p in payload.provisions:
            if not p.provision_code:
                errors.append("provision missing provision_code")
            errors.extend(_validate_provision_text(p))

    return errors

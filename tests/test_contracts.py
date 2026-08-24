"""Tests for staging contract validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestion.contracts import ActExtractionPayload, parse_staging_payload
from ingestion.validate import validate_payload

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_sample_act_payload_parses() -> None:
    raw = json.loads((SAMPLES / "cgst-s16-excerpt.json").read_text(encoding="utf-8"))
    payload = parse_staging_payload(raw)
    assert isinstance(payload, ActExtractionPayload)
    assert payload.provisions[0].provision_code == "CGST-S16"


def test_sample_act_payload_validates() -> None:
    raw = json.loads((SAMPLES / "cgst-s16-excerpt.json").read_text(encoding="utf-8"))
    errors = validate_payload(raw)
    assert errors == []


def test_rejects_empty_provision_text() -> None:
    raw = json.loads((SAMPLES / "cgst-s16-excerpt.json").read_text(encoding="utf-8"))
    raw["provisions"][0]["text_content"] = "too short"
    with pytest.raises(Exception):
        parse_staging_payload(raw)


def test_rejects_unknown_contract() -> None:
    raw = {"extraction": {"contract": "unknown.v99"}}
    with pytest.raises(ValueError, match="unknown extraction contract"):
        parse_staging_payload(raw)

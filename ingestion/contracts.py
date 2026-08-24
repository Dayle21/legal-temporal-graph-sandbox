"""Strict Pydantic contracts for legal extraction staging payloads.

Every provision promoted to Legal Core must conform to one of these contracts
before database write — no LLM free-form output reaches the graph.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ExtractionMethod(str, Enum):
    DETERMINISTIC_PARSER = "DETERMINISTIC_PARSER"
    LLM_ASSISTED = "LLM_ASSISTED"
    MANUAL = "MANUAL"


class ExtractionMeta(BaseModel):
    contract: Literal["act_extraction.v2", "rules_extraction.v1"]
    method: ExtractionMethod
    prompt_version: str
    extracted_at: datetime
    note: str | None = None


class DocumentMeta(BaseModel):
    document_id: str = Field(..., min_length=1, max_length=64)
    document_type: Literal["ACT", "RULE", "NOTIFICATION", "GAZETTE"]
    source_authority: str
    storage_path: str
    sha256: str = ""
    as_on_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_url: str | None = None


class InstrumentMeta(BaseModel):
    instrument_code: str = Field(..., min_length=1, max_length=64)
    instrument_type: Literal["ACT", "RULE", "NOTIFICATION"]
    short_title: str
    jurisdiction_id: str = "IN-CENTRAL"
    parent_instrument_code: str | None = None
    act_number: str | None = None
    enacted_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ProvisionPayload(BaseModel):
    provision_code: str = Field(..., min_length=1, max_length=128)
    provision_type: Literal["SECTION", "RULE", "NOTIFICATION", "CLAUSE"]
    label: str
    heading: str = ""
    text_content: str = Field(..., min_length=1)
    chapter: str | None = None
    effective_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    implements_sections: list[str] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)

    @field_validator("text_content")
    @classmethod
    def text_must_be_substantive(cls, value: str) -> str:
        if len(value.strip()) < 20:
            raise ValueError("text_content too short — likely truncated extraction")
        return value


class ActExtractionPayload(BaseModel):
    """Staging contract for Act sections (e.g. CGST-S16)."""

    extraction: ExtractionMeta
    document: DocumentMeta
    instrument: InstrumentMeta
    provisions: list[ProvisionPayload] = Field(..., min_length=1)

    @field_validator("extraction")
    @classmethod
    def contract_is_act(cls, meta: ExtractionMeta) -> ExtractionMeta:
        if meta.contract != "act_extraction.v2":
            raise ValueError("expected contract act_extraction.v2")
        return meta


class RulesExtractionPayload(BaseModel):
    """Staging contract for statutory rules (e.g. CGST-R36)."""

    extraction: ExtractionMeta
    document: DocumentMeta
    instrument: InstrumentMeta
    provisions: list[ProvisionPayload] = Field(..., min_length=1)

    @field_validator("extraction")
    @classmethod
    def contract_is_rules(cls, meta: ExtractionMeta) -> ExtractionMeta:
        if meta.contract != "rules_extraction.v1":
            raise ValueError("expected contract rules_extraction.v1")
        return meta


def parse_staging_payload(raw: dict) -> ActExtractionPayload | RulesExtractionPayload:
    """Parse and validate a staging JSON dict; raises ValidationError on mismatch."""
    contract = raw.get("extraction", {}).get("contract")
    if contract == "act_extraction.v2":
        return ActExtractionPayload.model_validate(raw)
    if contract == "rules_extraction.v1":
        return RulesExtractionPayload.model_validate(raw)
    raise ValueError(f"unknown extraction contract: {contract!r}")

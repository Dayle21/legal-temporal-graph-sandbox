"""
Parallel asyncio extraction orchestrator.

Demonstrates how large statute payloads are sliced into independent chunks,
processed concurrently against a schema-bound extractor endpoint, validated,
and merged into a single staging document.

Production note: the full legal-intelligence platform uses deterministic PDF
parsers (pypdf + regex) for authoritative ingestion. This module shows the
async orchestration pattern used when chunk-level LLM assist is enabled at
the review layer — each response must still pass contracts.py before promote.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion.contracts import ExtractionMethod, parse_staging_payload
from ingestion.validate import validate_payload

# ---------------------------------------------------------------------------
# Dummy extractor — simulates network latency + schema-bound JSON response.
# Replace EXTRACTOR_URL with a real endpoint in production.
# ---------------------------------------------------------------------------

EXTRACTOR_URL = "http://127.0.0.1:8000/extract-chunk"
SIMULATED_LATENCY_SEC = 0.05


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    label: str
    heading: str
    raw_text: str


@dataclass
class ChunkResult:
    chunk_id: str
    ok: bool
    provision: dict[str, Any] | None = None
    error: str | None = None


async def _dummy_extract_chunk(chunk: TextChunk) -> ChunkResult:
    """
    Stand-in for POST /extract-chunk.

    In demo mode we deterministically wrap the chunk text — no LLM call.
    When wired to a real service, use httpx.AsyncClient.post(EXTRACTOR_URL, json=...).
    """
    await asyncio.sleep(SIMULATED_LATENCY_SEC)

    if not chunk.raw_text.strip():
        return ChunkResult(chunk_id=chunk.chunk_id, ok=False, error="empty chunk")

    # Simulated schema-bound response from micro-model call
    provision = {
        "provision_code": f"CGST-S{chunk.label}",
        "provision_type": "SECTION",
        "label": chunk.label,
        "heading": chunk.heading,
        "text_content": chunk.raw_text.strip(),
        "cross_references": [],
    }
    return ChunkResult(chunk_id=chunk.chunk_id, ok=True, provision=provision)


async def extract_chunks_parallel(
    chunks: list[TextChunk],
    *,
    max_concurrency: int = 8,
) -> list[ChunkResult]:
    """Fire concurrent micro-extraction calls with bounded parallelism."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run(chunk: TextChunk) -> ChunkResult:
        async with semaphore:
            return await _dummy_extract_chunk(chunk)

    return list(await asyncio.gather(*[_run(c) for c in chunks]))


def merge_chunk_results(
    results: list[ChunkResult],
    *,
    document_meta: dict[str, Any],
    instrument_meta: dict[str, Any],
) -> dict[str, Any]:
    """Merge validated chunk outputs into a single staging payload."""
    failed = [r for r in results if not r.ok]
    if failed:
        raise ValueError(
            f"{len(failed)} chunk(s) failed: "
            + ", ".join(f"{r.chunk_id}: {r.error}" for r in failed[:3])
        )

    provisions = [r.provision for r in results if r.provision]
    provisions.sort(key=lambda p: int(p["label"]) if str(p["label"]).isdigit() else 0)

    return {
        "extraction": {
            "contract": "act_extraction.v2",
            "method": ExtractionMethod.LLM_ASSISTED.value,
            "prompt_version": "sandbox_async_v1",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        },
        "document": document_meta,
        "instrument": instrument_meta,
        "provisions": provisions,
    }


async def run_demo() -> None:
    """CLI demo: parallel-extract three CGST sections and validate merged JSON."""
    chunks = [
        TextChunk("ch-16", "16", "Eligibility and conditions for taking input tax credit", "(1) Every registered person shall…"),
        TextChunk("ch-17", "17", "Apportionment of credit", "(1) Where the goods or services…"),
        TextChunk("ch-18", "18", "Availability of credit in special circumstances", "(1) Subject to the provisions of…"),
    ]

    print(f"Extracting {len(chunks)} chunks in parallel (concurrency=8)…")
    results = await extract_chunks_parallel(chunks, max_concurrency=8)
    elapsed_chunks = len(results)
    ok = sum(1 for r in results if r.ok)
    print(f"  completed: {ok}/{elapsed_chunks} chunks OK")

    payload = merge_chunk_results(
        results,
        document_meta={
            "document_id": "DOC-GST-ACT-001",
            "document_type": "ACT",
            "source_authority": "India Code",
            "storage_path": "samples/cgst-act.pdf",
            "sha256": "",
            "as_on_date": "2026-06-11",
        },
        instrument_meta={
            "instrument_code": "CGST-2017",
            "instrument_type": "ACT",
            "short_title": "Central Goods and Services Tax Act, 2017",
            "act_number": "12 of 2017",
            "jurisdiction_id": "IN-CENTRAL",
            "enacted_date": "2017-07-01",
        },
    )

    # Pydantic schema validation
    parse_staging_payload(payload)
    business_errors = validate_payload(payload)
    if business_errors:
        print("VALIDATION FAILED:")
        for err in business_errors:
            print(f"  - {err}")
        sys.exit(1)

    print("VALIDATION OK — merged staging payload:")
    print(json.dumps(payload, indent=2)[:1200] + "\n…")


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()

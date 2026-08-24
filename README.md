# Temporal Legal Intelligence Platform — Sandbox

> Generic LLM vector systems fail at statutory timeline tracking because answers are **probabilistic**. This engine maps law as a **deterministic, version-controlled temporal graph** — provisions, amendments, effectivity windows, and cross-instrument relationships reconstructed as-of any date.

This folder is a **portfolio extract** from a larger production platform. It demonstrates three core patterns interviewers care about:

1. **Strict extraction contracts** (Pydantic) — no hallucinated structure reaches the database  
2. **Async parallel chunk processing** — concurrent micro-calls instead of one giant sequential prompt  
3. **Temporal SQL** — point-in-time state reconstruction via `effective_from` / `effective_to` intervals  

---

## Repository layout

```text
legal-temporal-graph-sandbox/
├── README.md
├── docs/FULL_ARCHITECTURE.md     ← full platform architecture (condensed)
├── ingestion/
│   ├── contracts.py              ← Pydantic staging schemas
│   ├── async_parser.py           ← asyncio parallel chunk orchestrator
│   └── validate.py               ← business-rule validation
├── queries/
│   └── state_reconstructor.sql   ← as-of date SQL queries
├── samples/
│   └── cgst-s16-excerpt.json     ← real GST ITC section (no PDFs shipped)
└── tests/
    └── test_contracts.py
```

---

## Quick start

Requires **Python 3.10+**.

```powershell
cd legal-temporal-graph-sandbox
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest -q
python -m ingestion.async_parser
```

Expected: tests pass; async demo prints a validated merged staging JSON for three parallel chunks.

---

## System vision & problem statement

Indian GST disputes hinge on **what the law said on date X** — not what a model vaguely remembers. Section 16(2)(aa), Rule 36(4), and Notif 49/2019 each have distinct effective windows. A RAG chatbot that retrieves "similar" chunks cannot answer:

- *Was the 20% ITC cap operative on 2019-10-09?*  
- *Which rule implements section 37 for documentary conditions?*  
- *What did S16(2)(aa) say before FA 2021?*

This platform treats law as **data with provenance**:

| Concept | Implementation |
|---------|----------------|
| Stable identity | `CGST-S16` never changes |
| Text changes | New `provision_versions` row |
| Notifications | `provision_amendments` edges |
| Cross-instrument links | `provision_relationships` graph |
| As-of reconstruction | Interval queries + amendment composer |

---

## Core technical architecture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         LEGAL CORE (public law)                          │
│  PostgreSQL :5434                                                        │
│  source_documents → provisions → provision_versions (temporal)         │
│  regulatory_notifications → provision_amendments                         │
│  provision_relationships (IMPLEMENTS, CROSS_REFERENCES)                  │
└─────────────────────────────────────────────────────────────────────────┘
         ▲ promote                           ▲ read-only by ID
         │                                   │
┌────────┴──────────────┐            ┌────────┴──────────────────────────┐
│ INGESTION PIPELINE    │            │ LAWYER CORE (private matters)      │
│ PDF → extract         │            │ PostgreSQL :5433                   │
│ → STAGING JSON        │            │ matters, entities (encrypted vault)│
│ → validate (contract) │            │ anonymisation review queue         │
│ → promote             │            │ matter_legal_context (ID refs only)│
└───────────────────────┘            └────────────────────────────────────┘
                                                │
                                                ▼
                                     anonymisation gate (llm_safe)
                                                │
                                                ▼
                                     temporal_engine + LLM reasoning
                                                │
                                                ▼
                                     citation verification → answer
```

**Data flow:**

```text
Raw PDF  →  Tokenizer/Parser  →  Staging JSON  →  Validation  →  Temporal Graph
                                                                      ↓
                                                          State Reconstructor (SQL)
                                                                      ↓
                                                          Operative text @ as_of_date
```

See [docs/FULL_ARCHITECTURE.md](docs/FULL_ARCHITECTURE.md) for the complete platform breakdown.

---

## Key technical decisions

### 1. Deterministic ingestion over LLM extraction

Statutory text is parsed with **pypdf + regex** (India Code PDF structure). LLMs never write law into the database. This eliminates hallucination at the source. The async parser in this sandbox shows how **parallel chunk orchestration** works when LLM assist is limited to review layers — every response still passes `contracts.py`.

### 2. Pydantic contracts before database promote

Staging payloads declare an explicit contract (`act_extraction.v2`, `rules_extraction.v1`). Invalid JSON never reaches PostgreSQL. See `ingestion/contracts.py` and `samples/cgst-s16-excerpt.json`.

### 3. Async parallel workers vs sequential mega-prompts

| Approach | Latency | Cost | Precision |
|----------|---------|------|-----------|
| One 150-page prompt | High | High | Drift / truncation |
| N parallel chunk calls | Low (bounded concurrency) | Linear | Per-chunk schema validation |

`ingestion/async_parser.py` uses `asyncio.gather` + `Semaphore(8)` to process independent section chunks concurrently.

### 4. Temporal intervals, not "latest text"

Provision versions and effectivity rows use half-open intervals:

```sql
effective_from <= :target_date
AND (effective_to >= :target_date OR effective_to IS NULL)
```

See `queries/state_reconstructor.sql`.

### 5. Dual-database isolation

Legal Core stores **public authoritative law**. Lawyer Core stores **client matters**. They share no tables. Lawyer Core references Legal Core by stable provision codes only.

---

## Privacy / security isolation blueprint

Client-side entity anonymisation operates **before any LLM network transit**:

```text
Register parties + confirmed aliases (intake)
        ↓
Paste matter text → replace only confirmed aliases
        ↓
Heuristics flag unmapped spans → human review queue
        ↓
Lawyer: MERGE | NEW_ENTITY | DISMISS
        ↓
Re-process until llm_safe = true
        ↓
Only anonymised text → LLM prompt
```

**Principles:**

- **Confirmed aliases only** — no fuzzy auto-merge of names or typos  
- **Encrypted vault** — real identities in `matter_entities.real_value_sealed`, never in prompts  
- **LLM gate** — API returns 422 until all review items resolved  
- **Legal Core never stores client data** — separation is architectural, not policy  

Full detail: [docs/FULL_ARCHITECTURE.md#anonymisation--llm-gate](docs/FULL_ARCHITECTURE.md).

---

## GST pilot example (from full platform)

| Code | Type | Role in ITC dispute |
|------|------|---------------------|
| CGST-S16 | Section | Eligibility + S16(2) conditions |
| CGST-S37 | Section | Outward supply / GSTR-1 furnishing |
| CGST-R36 | Rule | Documentary conditions + R36(4) 20% cap |

Sample staging JSON: `samples/cgst-s16-excerpt.json` (Section 16 excerpt).

---

## What this sandbox vs full platform

| This sandbox (~500 LOC) | Full `legal-intelligence` platform |
|-------------------------|-------------------------------------|
| Pydantic contracts | + PostgreSQL ORM models, Alembic migrations |
| Async chunk demo | + Deterministic PDF parsers (CGST/IGST/UTGST) |
| Temporal SQL | + SQLAlchemy client, amendment composer |
| Sample JSON | + FastAPI APIs, React workbench, Docker Compose |
| Architecture docs | + Matter AI gateway, legal updates feed |

---

## License & data

Sample JSON contains **public statutory text** (India Code). No client data. No PDFs included.

---

## Author

Lisa Dayle Carvalho

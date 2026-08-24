# Full Platform Architecture

Condensed reference for the production **legal-intelligence** system that this sandbox extracts from.

---

## Core principle

**Legal Core** stores public authoritative law. **Lawyer Core** stores private matter data. They never share tables or document storage.

Lawyer Core may **reference** Legal Core by stable ID (`CGST-S16`). Legal Core must never store client-identifiable data.

---

## Layer model (deterministic cognitive architecture)

```text
LAYER 0  RAW PDF           Immutable file on disk + SHA256
LAYER 1  EXTRACTED TEXT    Deterministic PDF parse (pypdf)
LAYER 2  STRUCTURED JSON   Fixed schema per document type (contracts.py)
LAYER 3  VALIDATION        JSON Schema + business rules (no LLM)
LAYER 4  CANONICAL DB      Legal Core PostgreSQL
LAYER 5  REASONING         Applicability → retrieval → LLM (gated)
LAYER 6  VERIFICATION      Citation check against Legal Core
```

**Principles:**

1. No crawling — files manually downloaded from official sources (India Code, CBIC)  
2. No LLM in ingestion — deterministic parsers + fixed schemas  
3. Provenance — every provision links to `source_document_id` and `as_on_date`  
4. Stable IDs — `CGST-S16` never changes; text changes create new `provision_versions`  
5. Separation — Lawyer Core never stores law text; Legal Core never stores client data  

---

## Database separation

### Legal Core (`127.0.0.1:5434`)

| Table | Purpose |
|-------|---------|
| `source_documents` | PDF provenance, SHA256, storage path |
| `legal_instruments` | Acts, Rules (`CGST-2017`, `CGST-RULES-2017`) |
| `provisions` | Stable nodes (`CGST-S16`, `CGST-R36`) |
| `provision_versions` | Temporal text snapshots |
| `legal_effectivity` | In force / repealed / not commenced |
| `regulatory_notifications` | CBIC notifications |
| `provision_amendments` | Notification → provision change edges |
| `provision_relationships` | Graph: IMPLEMENTS, CROSS_REFERENCES |
| `cases`, `case_paragraphs` | Judgment corpus (future) |
| `extraction_runs` | Pipeline audit trail |

### Lawyer Core (`127.0.0.1:5433`)

| Table | Purpose |
|-------|---------|
| `matters`, `proceedings`, `parties` | Case management |
| `matter_entities` | Encrypted identity vault |
| `matter_entity_aliases` | Confirmed surface forms → tokens |
| `anonymisation_review_items` | Human review queue |
| `matter_documents` | Client uploads (anonymised text) |
| `matter_legal_context` | ID references into Legal Core only |
| `matter_legal_alerts` | Amendment impact notifications |

---

## Ingestion pipeline (production)

```text
OFFICIAL PDF
    │
    ▼
scripts/extract_pdf_text.py          (pypdf, deterministic)
    │
    ▼
scripts/extract_gst_provisions.py    (regex section/rule parser)
    │
    ▼
data/gst/staging/*.json              (contract-bound payload)
    │
    ▼
scripts/validate_staging.py          (business rules)
    │
    ▼
scripts/promote_staging.py           (Legal Core PostgreSQL)
```

**Supported instruments (in progress):**

| Instrument | Sections/Rules |
|------------|----------------|
| CGST Act 2017 | Full act ingest |
| CGST Rules 2017 | R1–R162 |
| IGST Act / Rules | Full |
| UTGST Act | 29 sections |

---

## Temporal engine

**Module:** `services/temporal_engine/engine.py`

```python
# Pseudocode flow
version = get_provision_version_as_of(provision_id, as_of_date)
amendments = get_amendments_for_provision(provision_id, as_of_date)
operative_text = compose_text_at_as_of(version.text_content, amendments)
```

**Module:** `services/legal_text/composer.py`

Applies `INSERT` / `SUBSTITUTE` amendments to base corpus text by sub-rule label (e.g. Rule 36(4)). Last amendment per label wins.

**SQL equivalent:** `queries/state_reconstructor.sql` in this sandbox.

---

## Graph relationships

Example edges in the GST ITC vertical:

```text
CGST-R36  ──IMPLEMENTS──▶  CGST-S31, CGST-S34, CGST-S37
CGST-R36  ──CROSS_REF───▶  CGST-S16 (via section references in rule text)
CGST-S16  ──CROSS_REF───▶  CGST-S37, CGST-S49, CGST-S39
```

Notifications attach as amendment edges:

```text
NOTIF-49-2019-CT  ──SUBSTITUTE──▶  CGST-R36 (4)   effective 2019-10-09
NOTIF-75-2019-CT  ──INSERT──────▶  CGST-R36 (4)   effective 2020-01-01
```

---

## Anonymisation & LLM gate

**Modules:** `services/anonymiser/service.py`, `services/anonymiser/matter_service.py`

```text
Register parties + aliases (intake)
        ↓
Paste / upload text → POST .../documents/ingest-text
        ↓
Confirmed aliases replaced; unmapped → review queue
        ↓
Lawyer: MERGE → PERSON_1 | NEW_ENTITY | DISMISS
        ↓
POST .../documents/{id}/reprocess
        ↓
Re-preview until llm_safe: true → document status READY
        ↓
POST .../ai/ask (same gate on questions)
        ↓
Only concealed text → LLM prompt
```

**Heuristics flagged for review (never auto-replaced):**

- Person names, organisations (`M/s. …`)  
- GSTIN, PAN, phone, email  
- Case numbers (`FIA/…`, `WP/…`)  

Real identities live in `matter_entities.real_value_sealed` — never in prompts or Legal Core.

---

## Application services (full platform)

| Service | Port | Role |
|---------|------|------|
| `apps/legal-ingestion-api` | 8001 | Staging upload, validation |
| `apps/lawyer-api` | 8000 | Matters, anonymisation, legal research |
| `apps/lawyer-web` | 5173 | Matter dashboard, research, updates |
| `apps/ingestion-workbench` | 5174 | Document ingestion UI |

**Key service modules:**

| Module | Purpose |
|--------|---------|
| `services/legal_research/service.py` | Provision search + as-of detail |
| `services/legal_updates/feed.py` | Amendment notification feed |
| `services/matter_legal_context/builder.py` | Attach provisions to matters |
| `services/applicability_engine/engine.py` | Which instruments apply |
| `services/citation_verifier/verifier.py` | Post-LLM citation check |
| `packages/legal_core_client/client.py` | Read-only Legal Core access |

---

## Matter workflow example (GST ITC)

**Matter:** `MTR-GST-ITC-001` — input tax credit dispute, as-of **2019-10-09**

Attached provisions:

- `CGST-S16` — eligibility conditions  
- `CGST-S37` — outward supply furnishing  
- `CGST-R36` — documentary requirements + 20% cap (Notif 49/2019)  

Temporal reconstruction ensures Rule 36(4) bracketed text reflects the notification in force on the dispute date, not a later amendment.

---

## Extension roadmap

1. Full CGST Rules R1–R162 promotion  
2. FA 2021 + Notif 39/2021 for S16(2)(aa) temporal accuracy  
3. IGST-S20 / UTGST-S21 → CGST APPLIES relationship edges  
4. Compensation Cess Act profile  
5. Case law ingestion with paragraph-level citations  
6. SGST state acts — case-driven only  

---

## Mapping sandbox → production

| Sandbox file | Production equivalent |
|--------------|----------------------|
| `ingestion/contracts.py` | `scripts/validate_staging.py` + staging JSON schemas |
| `ingestion/async_parser.py` | Parallel chunk pattern; prod uses `extract_gst_provisions.py` |
| `ingestion/validate.py` | `scripts/validate_staging.py` |
| `queries/state_reconstructor.sql` | `packages/legal_core_client/client.py` |
| `samples/cgst-s16-excerpt.json` | `data/gst/staging/cgst-act-s16-sample.json` |

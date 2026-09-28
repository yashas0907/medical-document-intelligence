# MedIntel — Technical Architecture

Version 1.0.0 · pipeline `1.0.0` · prompt `p1`

## 1. System overview

```mermaid
flowchart TB
    subgraph Client
        UI[Next.js 15 frontend]
    end

    subgraph Backend[FastAPI backend]
        API[API layer\nauth + documents + qa + summaries + compare]
        WP[Worker pool\nThreadPoolExecutor]
        PS[Processing pipeline]
        RAG[RAG service]
        AN[Analysis service\nsummaries + compare + contradictions + timeline]
        RET[Retrieval store\nfingerprinted cache]
    end

    subgraph Storage
        DB[(SQLAlchemy 2\nSQLite / PostgreSQL)]
        FS[(File storage\nopaque names, owner-scoped)]
    end

    subgraph ML[ML components]
        P[parsers\nPDF / DOCX / TXT]
        O[OCR adapter\nTesseract]
        CL[cleaning]
        SD[structure detection]
        EE[entity + measurement extraction\nrules]
        TE[table extraction]
        CH[chunker]
        EM[embedding provider\nTF-IDF | OpenAI-compatible]
        HR[hybrid retriever\nTF-IDF + BM25 + RRF]
        GE[grounded engine\nextractive + optional LLM]
        SEC[security\ninjection scan + neutralize]
    end

    UI -->|REST + JWT| API
    API -->|submit job| WP
    WP --> PS
    PS --> P --> O --> CL --> SD --> EE
    PS --> TE
    SD --> CH
    CH --> DB
    API --> RAG --> RET --> HR
    HR --> EM
    RAG --> GE
    GE --> SEC
    API --> AN
    PS --> FS
    API --> DB
```

## 2. Data flow — upload to answer

1. **Upload** (`POST /documents`): validate size/extension/emptiness →
   SHA-256 duplicate check → sanitize filename → store bytes under opaque name
   → insert `documents` row → submit processing job to worker pool → `201`
   immediately (user never waits on OCR).
2. **Processing job** (worker thread, own DB session):
   - parse (per-format adapter) → pages with `extraction_method`
     (`text` / `ocr` / `ocr-failed` / `empty`) and `ocr_confidence`
   - clean (repeated header/footer fingerprints, control chars)
   - structure detection (title + sections; medical vocabulary boost)
   - table extraction (header + rows + page; rows → typed measurements)
   - entity extraction (rules; per section; snippet + page provenance)
   - chunking (structure-aware; tables never split; min-merge)
   - persist everything with FK provenance chain
   - document status `completed` / `failed` with message
3. **Ask** (`POST /documents/{id}/ask`): load chunks → build/reuse
   fingerprinted retriever → hybrid search → evidence validation →
   extractive selection (query-relevance ranked, citation-carrying) →
   optional LLM rewriter (validated) → persist conversation + citations +
   model_run → respond with `groundedness`, `evidence_coverage`, citations.
4. **Compare** (`POST /documents/compare`): load both docs' measurements +
   entities → deterministic keyed diff → rows with both-sided evidence cells
   → summary (added/removed/changed/unchanged counts).

## 3. Design decisions

| Decision | Rationale |
|---|---|
| **Extractive grounded engine as default** | Deterministic → testable, offline, zero-cost, and *cannot* hallucinate: answers are composed of stored source sentences. LLM is an optional rewriter, not the source of truth. |
| **Hybrid retrieval (TF-IDF + BM25 + RRF)** | Medical queries are heavy on exact terminology (drug names, `HbA1c`, `WBC`) where lexical BM25 wins; paraphrase needs vector-ish similarity. RRF fuses without score-scale assumptions. |
| **Abbreviation-aware query expansion** | "BP" vs "blood pressure" is the classic medical retrieval failure. A verified abbreviation map bridges query and document vocabulary at both retrieval and sentence ranking. |
| **Per-document index + in-process cache with fingerprint** | Documents are private per user — per-document indexes make cross-user leakage impossible by construction. Fingerprint = (pipeline version, embedding model, chunk content hash) → any pipeline change rebuilds. |
| **Threaded worker pool vs Celery** | Single-node deployment reality: FastAPI + bounded ThreadPoolExecutor gives real async processing without a broker. The `process_document(db, doc, bytes)` boundary is broker-agnostic — Celery can wrap it verbatim. |
| **Rules-based extraction** | Reproducible, auditable, free, and *honest* — it extracts only what is explicitly written, which is the product's contract. LLM extraction would be probabilistic and unauditable. |
| **SQLite dev / Postgres prod** | Zero-setup local development; production path fully exercised via Docker (pgvector provisioned for future dense embeddings). |
| **TF-IDF local embedder** | Zero-dependency, zero-cost default that performs well for per-document QA (eval MRR 0.889). Provider interface keeps the upgrade path open. |

## 4. Provenance chain

```
answer sentence ──ref──▶ citation row ──FK──▶ document
                                   └──FK────▶ chunk ──FK──▶ section
                                     (page_number, quote persisted)
measurement ──FK──▶ document (page, snippet, table_row JSON)
table row ──▶ table_extraction (page, header, rows)
entity ──▶ section + page + snippet (+chunk when available)
model_run ──▶ provider/model/prompt_version/pipeline_version/duration
```

Every user-visible claim resolves to stored bytes. Fake citations are
structurally impossible because citations are foreign keys, not strings.

## 5. Grounding rules (enforced in code)

1. Retrieval must return passages (else refuse: "No passages were retrieved…").
2. Query evidence support must be non-trivial (else refuse).
3. Answer sentences are *selected source text*, each mapped to a citation ref.
4. Sentence must share content tokens with the question (unless it's a
   single-concept category question, where retrieval did the work).
5. LLM mode: any output sentence lacking a valid `(n)` marker or failing
   source-overlap validation is dropped.
6. `insufficient_evidence: true` responses are first-class — the UI renders
   them as explicit not-found, not as failure.

## 6. Security model

| Threat | Defense |
|---|---|
| Prompt injection in documents | content is data; injection scanner logs security events; neutralizer strips instruction-like sequences pre-LLM and in quoted answers; trusted system prompt never contains document text |
| Malicious PDFs | pymupdf parse errors → clean 422; no JS/embedded-file execution; size caps |
| Path traversal | filename sanitization; stored names are opaque tokens; explicit stored-filename validation |
| Oversized uploads | pre-read byte cap → 413 with limits in details |
| Unauthorized access | JWT (HS256, exp-bound); owner-scoped queries; FK-enforced isolation; 403/404 without data leak |
| Secret leakage | .env only, never committed; secrets never logged; safe error messages (no tracebacks to clients) |
| Abuse | per-IP rate limits (slowapi) |
| Sensitive logging | logs contain IDs/metadata/durations, never document content |

## 7. Observability

- `model_runs`: one row per pipeline stage / AI call — kind, provider, model,
  prompt_version, pipeline_version, duration_ms, success, error_code, meta
  (counts, groundedness, retrieval ms).
- `X-Process-Time-Ms` response header.
- Answer payloads persist `groundedness`, `evidence_coverage`, `method`,
  `retrieval_ms`, and `model_meta` — reproducible AI results.
- `GET /api/v1/runs` exposes the model-run log; `audit_logs` records
  security-relevant actions.

## 8. Evaluation methodology

`evals/run_eval.py` ingests the 7 synthetic fixtures (fictional data), runs
the real pipeline, and computes:

- **Extraction** — set-match P/R/F1 against gold lists (medications,
  measurement names, ISO dates) per document, including table-PDF.
- **Retrieval** — 9 labeled (query → gold snippet) pairs: Recall@3, Recall@6,
  MRR.
- **RAG** — answerable cases checked for exact expected value in the answer;
  unanswerable case must refuse; groundedness = cited-sentence share;
  citation validity = every sentence ref resolves to a real citation.
- **Comparison** — P/R against gold changed/unchanged value sets.
- **Contradictions** — P/R against gold conflict set.

Results are written to `evals/results/eval_report.json` and summarized in the
README. The dataset is small and synthetic — regression-grade, not
research-grade.

## 9. Scaling notes

- Worker pool size is env-tunable; processing is CPU-bound (OCR dominates).
- For multi-node: replace the pool submit with Celery; `process_document` is
  the exact task boundary.
- For corpus growth: move embeddings to pgvector (provisioned), swap
  `EMBEDDING_PROVIDER`, add HNSW index — retriever interface unchanged.
- Caches: retriever index memo (fingerprint-validated), duplicate SHA-256
  short-circuit; both per-user safe.

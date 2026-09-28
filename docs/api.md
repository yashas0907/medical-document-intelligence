# API Reference (v1)

Base URL: `/api/v1` · Interactive docs: `/api/docs` (Swagger) · `/api/redoc`

All endpoints except `/auth/*` and `/health` require `Authorization: Bearer <token>`.

Error shape (all non-2xx):
```json
{ "error": { "code": "not_found", "message": "Document not found", "details": {} } }
```

## Auth

| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/auth/register` | `{email, password≥8}` | 201 `{id, email, role}` |
| POST | `/auth/login` | `{email, password}` | 200 `{access_token, token_type, expires_in}` — rate-limited |

## Documents

| Method | Path | Notes |
|---|---|---|
| POST | `/documents` | multipart `file` (.pdf/.docx/.txt, ≤30MB). Duplicate SHA-256 → 422 with existing id. Returns immediately; processing is queued. |
| GET | `/documents` | list, newest first (`?skip&limit`) |
| GET | `/documents/stats` | per-user corpus stats |
| GET | `/documents/{id}` | detail |
| DELETE | `/documents/{id}` | 204; cascades DB rows + purges files |
| POST | `/documents/{id}/process` | 202; re-run pipeline |
| GET | `/documents/{id}/status` | `{status, status_message, page_count, sections, chunks, entities, measurements, tables}` |
| GET | `/documents/{id}/sections` | detected sections |
| GET | `/documents/{id}/pages?skip&limit` | page text + `extraction_method` + `ocr_confidence` |
| GET | `/documents/{id}/entities?type=` | extracted entities (filterable) |
| GET | `/documents/{id}/measurements` | typed lab values |
| GET | `/documents/{id}/tables` | preserved tables |

## Q&A

`POST /documents/{id}/ask` — `{question, conversation_id?, document_ids?}` →

```json
{
  "answer": "Metformin 500 mg twice daily. [1]",
  "answer_sentences": [{"text": "...", "citation_refs": ["[1]"]}],
  "citations": [{"ref": "[1]", "document_id": "...", "page_number": 1,
                  "section_title": "Medications", "chunk_id": "...", "quote": "Metformin 500 mg..."}],
  "evidence": [{"chunk_id": "...", "page_number": 1, "text": "...", "score": 0.031}],
  "groundedness": 1.0,
  "evidence_coverage": 0.5,
  "method": "extractive",
  "insufficient_evidence": false,
  "model_meta": {"provider": "extractive", "model": "extractive-v1",
                  "prompt_version": "p1", "pipeline_version": "1.0.0"}
}
```

`insufficient_evidence: true` means the system **refused** — answer explains
what was not found. Ask requires `status=completed`.

## Summaries

`POST /documents/{id}/summarize` — `{mode: quick|detailed|key_findings|timeline|structured, section_id?, max_words?}`

Structured mode returns fixed sections; absent information is
`"Not found in the document."` with `found: false`.

## Comparison / contradictions / timeline / citations

| Method | Path | Notes |
|---|---|---|
| POST | `/documents/compare` | `{document_a_id, document_b_id}` → rows: `{category, item, a, b, change_type: added|removed|changed|unchanged, change_note}` + citations |
| POST | `/documents/{id}/contradictions?compare_with=` | value/date/unit conflicts; omit `compare_with` for internal scan |
| GET | `/documents/{id}/timeline` | chronological events from date entities |
| GET | `/documents/{id}/citations` | citation log for the document |

## System

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | db/storage/llm/ocr status — unauthenticated |
| GET | `/me` | current user |
| GET | `/runs?kind=&limit=` | model-run observability log |

## Status codes

401 unauthenticated · 403 not your document · 404 missing · 409 conflict ·
413 too large · 415/422 validation · 429 rate limited · 500 processing · 503 dependency down

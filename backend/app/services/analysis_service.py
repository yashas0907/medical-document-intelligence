"""Summaries, timelines, comparisons, contradictions — service layer."""
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models
from app.ml.comparison.contradictions import detect_contradictions as _detect_contradictions
from app.ml.comparison.engine import compare_documents as _compare_documents
from app.ml.summaries.generator import summarize as _summarize
from app.ml.versions import PIPELINE_VERSION

log = get_logger(__name__)


def _doc_sections(db: Session, document_id: str) -> list[dict]:
    rows = db.scalars(
        select(models.Section).where(models.Section.document_id == document_id)
        .order_by(models.Section.order_index)
    ).all()
    out = []
    for r in rows:
        chunks = db.scalars(
            select(models.Chunk).where(
                models.Chunk.document_id == document_id,
                models.Chunk.section_id == r.id,
            ).order_by(models.Chunk.chunk_index)
        ).all()
        text = "\n\n".join(c.text for c in chunks)
        out.append({
            "id": r.id, "title": r.title, "text": text,
            "page_number": r.page_number, "order_index": r.order_index,
        })
    return out


def _doc_chunks(db: Session, document_id: str) -> list[dict]:
    rows = db.scalars(
        select(models.Chunk).where(models.Chunk.document_id == document_id)
        .order_by(models.Chunk.chunk_index)
    ).all()
    sec_ids = {r.section_id for r in rows if r.section_id}
    titles = {}
    if sec_ids:
        secs = db.scalars(select(models.Section).where(models.Section.id.in_(sec_ids))).all()
        titles = {s.id: s.title for s in secs}
    return [
        {
            "id": r.id, "text": r.text, "page_number": r.page_number,
            "section_id": r.section_id, "section_title": titles.get(r.section_id),
            "is_table_chunk": r.is_table_chunk,
        }
        for r in rows
    ]


def _doc_entities(db: Session, document_id: str) -> list[dict]:
    rows = db.scalars(
        select(models.ExtractedEntity)
        .where(models.ExtractedEntity.document_id == document_id)
        .order_by(models.ExtractedEntity.entity_type, models.ExtractedEntity.raw_text)
    ).all()
    return [
        {
            "id": r.id, "entity_type": r.entity_type, "raw_text": r.raw_text,
            "normalized_text": r.normalized_text,
            "normalized_confidence": r.normalized_confidence,
            "page_number": r.page_number, "section_id": r.section_id,
            "chunk_id": r.chunk_id, "source_snippet": r.source_snippet,
        }
        for r in rows
    ]


def _doc_measurements(db: Session, document_id: str) -> list[dict]:
    rows = db.scalars(
        select(models.Measurement).where(models.Measurement.document_id == document_id)
    ).all()
    return [
        {
            "id": r.id, "name": r.name, "value_raw": r.value_raw, "value_num": r.value_num,
            "unit": r.unit, "reference_range": r.reference_range, "flag": r.flag,
            "page_number": r.page_number, "chunk_id": r.chunk_id,
            "source_snippet": r.source_snippet,
        }
        for r in rows
    ]


def build_summary(db: Session, document: models.Document, mode: str,
                  section_id: str | None = None, max_words: int = 250) -> dict:
    t0 = time.perf_counter()
    sections = _doc_sections(db, document.id)
    chunks = _doc_chunks(db, document.id)
    entities = _doc_entities(db, document.id)

    # section vocab match not persisted; recompute cheaply for structured mode
    from app.ml.ingestion.structure import SECTION_VOCAB
    for s in sections:
        s["matched_vocab"] = SECTION_VOCAB.get(s["title"].lower().strip(), None)

    out = _summarize(
        doc_id=document.id,
        title=document.title,
        mode=mode,
        sections=sections,
        chunks=chunks,
        entities=entities,
        doc_date=document.doc_date,
        doc_type=document.doc_type,
        max_words=max_words,
        section_id=section_id,
    )
    ms = int((time.perf_counter() - t0) * 1000)
    db.add(models.ModelRun(
        kind="summarize", provider="extractive", model="summarizer-v1",
        pipeline_version=PIPELINE_VERSION, duration_ms=ms, success=True,
        document_id=document.id, meta={"mode": mode},
    ))
    db.commit()
    return {
        "document_id": document.id,
        "mode": mode,
        "title": out.title,
        "summary_text": out.summary_text,
        "sections": [
            {"label": s.label, "content": s.content,
             "citation_refs": s.citation_refs, "found": s.found}
            for s in out.sections
        ],
        "citations": out.citations,
        "model_meta": out.model_meta,
    }


def build_timeline(db: Session, document: models.Document) -> dict:
    entities = _doc_entities(db, document.id)
    events: list[dict] = []
    seen_dates: dict[str, dict] = {}

    for e in entities:
        if e["entity_type"] != "date" or not e.get("normalized_text"):
            continue
        d = e["normalized_text"]
        if d not in seen_dates:
            seen_dates[d] = {
                "date": d, "date_confidence": "high" if (e.get("normalized_confidence") or 0) >= 0.9 else "low",
                "source": document.title, "document_id": document.id,
                "page_number": e.get("page_number"), "items": [], "citation_refs": [],
            }
            events.append(seen_dates[d])
        snippet = e.get("source_snippet", "")
        item = snippet[:180]
        if item and item not in seen_dates[d]["items"]:
            seen_dates[d]["items"].append(item)

    events.sort(key=lambda ev: ev["date"] or "")
    return {
        "document_id": document.id,
        "events": events,
        "unpositioned": [],
    }


def run_comparison(db: Session, user, doc_a: models.Document, doc_b: models.Document) -> dict:
    t0 = time.perf_counter()
    a_meas = _doc_measurements(db, doc_a.id)
    b_meas = _doc_measurements(db, doc_b.id)
    a_ent = _doc_entities(db, doc_a.id)
    b_ent = _doc_entities(db, doc_b.id)

    out = _compare_documents(
        doc_a={"id": doc_a.id, "title": doc_a.title, "date": doc_a.doc_date},
        doc_b={"id": doc_b.id, "title": doc_b.title, "date": doc_b.doc_date},
        a_measurements=a_meas, b_measurements=b_meas,
        a_entities=a_ent, b_entities=b_ent,
    )
    ms = int((time.perf_counter() - t0) * 1000)
    payload = {
        "doc_a_id": out.doc_a_id, "doc_b_id": out.doc_b_id,
        "doc_a_title": out.doc_a_title, "doc_b_title": out.doc_b_title,
        "doc_a_date": out.doc_a_date, "doc_b_date": out.doc_b_date,
        "rows": [
            {
                "category": r.category, "item": r.item,
                "a": _cell(r.a), "b": _cell(r.b),
                "change_type": r.change_type, "change_note": r.change_note,
            }
            for r in out.rows
        ],
        "citations": out.citations,
        "summary": out.summary,
    }
    db.add(models.ComparisonJob(
        user_id=user.id, doc_a_id=doc_a.id, doc_b_id=doc_b.id,
        status="completed", result={"summary": out.summary, "rows": len(out.rows)},
    ))
    db.add(models.ModelRun(
        kind="compare", provider="deterministic", model=out.version,
        pipeline_version=PIPELINE_VERSION, duration_ms=ms, success=True,
    ))
    db.commit()
    return payload


def _cell(c) -> dict | None:
    if c is None:
        return None
    return {
        "doc_id": c.doc_id, "doc_title": c.doc_title, "value": c.value,
        "citation_ref": getattr(c, "ref", None),
        "page_number": c.page_number,
    }


def run_contradictions(db: Session, document: models.Document,
                       other: models.Document | None = None) -> dict:
    t0 = time.perf_counter()
    a_meas = _doc_measurements(db, document.id)
    a_ent = _doc_entities(db, document.id)
    if other is None:
        b_meas, b_ent = a_meas, a_ent
        doc_b = None
    else:
        b_meas = _doc_measurements(db, other.id)
        b_ent = _doc_entities(db, other.id)
        doc_b = {"id": other.id, "title": other.title, "date": other.doc_date}

    out = _detect_contradictions(
        doc_a={"id": document.id, "title": document.title, "date": document.doc_date},
        doc_b=doc_b,
        a_measurements=a_meas, b_measurements=b_meas,
        a_entities=a_ent, b_entities=b_ent,
    )
    ms = int((time.perf_counter() - t0) * 1000)
    db.add(models.ModelRun(
        kind="contradictions", provider="deterministic", model=out.version,
        pipeline_version=PIPELINE_VERSION, duration_ms=ms, success=True,
        document_id=document.id,
    ))
    db.commit()
    return {
        "document_id": out.document_id,
        "compared_with": out.compared_with,
        "contradictions": [
            {
                "type": c.type, "severity": c.severity, "confidence": c.confidence,
                "explanation": c.explanation,
                "a": {
                    "claim": c.a.claim, "document_id": c.a.document_id,
                    "document_title": c.a.document_title,
                    "page_number": c.a.page_number, "quote": c.a.quote,
                    "section_title": c.a.section_title,
                },
                "b": {
                    "claim": c.b.claim, "document_id": c.b.document_id,
                    "document_title": c.b.document_title,
                    "page_number": c.b.page_number, "quote": c.b.quote,
                    "section_title": c.b.section_title,
                },
            }
            for c in out.contradictions
        ],
        "notes": out.notes,
    }

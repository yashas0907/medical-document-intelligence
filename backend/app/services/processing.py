"""Document processing pipeline (runs inside worker jobs).

upload → validate → extract(+OCR) → clean → structure → entities/tables →
chunk → persist. Progress + failures recorded on the Document row; ModelRun
rows capture per-stage latency for observability.
"""
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ProcessingError
from app.core.logging import get_logger
from app.db import models
from app.ml.chunking.chunker import chunk_document, serialize_table
from app.ml.extraction.entities import extract_from_table_row, extract_from_text
from app.ml.ingestion.cleaning import clean_pages
from app.ml.ingestion.parsers import get_parser_for_extension
from app.ml.ingestion.structure import detect_structure
from app.ml.ocr import get_ocr_provider
from app.ml.versions import ENTITY_EXTRACTOR_VERSION, PIPELINE_VERSION
from app.services import storage

log = get_logger(__name__)


def _model_run(db: Session, kind: str, provider: str, model: str, ms: int,
               document_id: str, success: bool = True, error_code: str | None = None,
               meta: dict | None = None) -> None:
    db.add(models.ModelRun(
        kind=kind, provider=provider, model=model, prompt_version="",
        pipeline_version=PIPELINE_VERSION, document_id=document_id,
        duration_ms=int(ms), success=success, error_code=error_code,
        meta=meta or {},
    ))
    db.commit()


def process_document(db: Session, document: models.Document, file_bytes: bytes) -> models.Document:
    settings = get_settings()
    t0 = time.perf_counter()
    document.status = "processing"
    document.status_message = None
    db.commit()

    try:
        ext = storage.extension_of(document.original_filename)
        parser = get_parser_for_extension(ext)

        # ---- OCR provider resolution ------------------------------------
        ocr = get_ocr_provider(settings.ocr_provider, settings.tesseract_cmd)

        # ---- Extraction (+ OCR per scanned page) --------------------------
        t_x = time.perf_counter()
        extracted = parser.extract(
            file_bytes, ocr, settings.max_pages_per_doc, settings.max_pages_ocr
        )
        _model_run(db, "extract", "pymupdf" if ext == "pdf" else parser.name, parser.name,
                  (time.perf_counter() - t_x) * 1000, document.id,
                  meta={"pages": extracted.page_count,
                        "ocr_available": ocr.available()})

        if extracted.page_count == 0:
            raise ProcessingError("No pages could be extracted from this document")

        # ---- Cleaning ------------------------------------------------------
        cleaned_texts, _report = clean_pages([p.text for p in extracted.pages])
        for p, ctext in zip(extracted.pages, cleaned_texts, strict=True):
            p.text = ctext if ctext or p.extraction_method != "text" else p.text

        total_chars = sum(len(p.text) for p in extracted.pages)
        if total_chars < 10:
            failed_pages = [p.page_number for p in extracted.pages
                            if p.extraction_method in ("ocr-failed", "empty")]
            raise ProcessingError(
                "Document contains no extractable text"
                + (f" (pages {failed_pages[:5]} appear to be scanned images and OCR "
                   f"is {'unavailable' if not ocr.available() else 'failed to read them'})"
                   if failed_pages else "")
            )

        # ---- Persist pages --------------------------------------------------
        for p in extracted.pages:
            db.add(models.Page(
                document_id=document.id,
                page_number=p.page_number,
                extraction_method=p.extraction_method,
                ocr_confidence=p.ocr_confidence,
                char_count=p.char_count,
                text=p.text,
            ))

        # ---- Structure -------------------------------------------------------
        page_pairs = [(p.page_number, p.text) for p in extracted.pages]
        title, detected = detect_structure(page_pairs)

        section_rows: dict[str, models.Section] = {}
        for sec in detected:
            row = models.Section(
                document_id=document.id,
                title=sec.title[:290],
                section_type=sec.section_type,
                page_number=sec.page_number,
                order_index=sec.order_index,
                char_count=len(sec.text),
            )
            db.add(row)
            db.flush()
            section_rows[sec.title] = row

        # ---- Tables ----------------------------------------------------------
        t_tab = time.perf_counter()
        table_count = 0
        for p in extracted.pages:
            for tab in p.tables:
                if not tab.header or not tab.rows:
                    continue
                # map columns by header names
                header = [h.lower() for h in tab.header]

                def col(names: tuple[str, ...], hdr: list[str] = header) -> int | None:
                    for n in names:
                        if n in hdr:
                            return hdr.index(n)
                    return None
                c_test = col(("test", "parameter", "name", "analyte", "lab", "lab test"))
                c_val = col(("value", "result", "results", "numeric value"))
                c_unit = col(("unit", "units", "uom"))
                c_ref = col(("reference range", "ref range", "range", "reference"))
                c_flag = col(("flag", "abnormal flag"))
                row = models.TableExtraction(
                    document_id=document.id,
                    page_number=p.page_number,
                    table_index=table_count,
                    header=tab.header,
                    rows=tab.rows,
                    row_count=len(tab.rows),
                )
                db.add(row)
                table_count += 1
                # structured measurements from table rows
                if c_test is not None and c_val is not None:
                    for r in tab.rows:
                        if len(r) <= max(c_test, c_val):
                            continue
                        rowd = {
                            "test": r[c_test], "value": r[c_val],
                            "unit": r[c_unit] if c_unit is not None and len(r) > c_unit else "",
                            "reference_range": r[c_ref] if c_ref is not None and len(r) > c_ref else "",
                            "flag": r[c_flag] if c_flag is not None and len(r) > c_flag else "",
                        }
                        for hit in extract_from_table_row(rowd, p.page_number):
                            db.add(models.Measurement(
                                document_id=document.id,
                                page_number=p.page_number,
                                name=hit.name[:190],
                                value_raw=hit.value_raw[:90],
                                value_num=hit.value_num,
                                unit=hit.unit,
                                reference_range=hit.reference_range[:90] if hit.reference_range else None,
                                flag=hit.flag,
                                source_snippet=hit.source_snippet,
                                table_row=hit.table_row,
                            ))
        _model_run(db, "tables", "rules", ENTITY_EXTRACTOR_VERSION,
                  (time.perf_counter() - t_tab) * 1000, document.id,
                  meta={"tables": table_count})

        # ---- Entities (per section) + measurements (text) ---------------------
        t_e = time.perf_counter()
        entity_count = 0
        measurement_count = 0
        for sec in detected:
            sec_row = section_rows.get(sec.title)
            hits = extract_from_text(sec.text, sec.page_number,
                                     section_id=sec_row.id if sec_row else None)
            for h in hits.entities:
                db.add(models.ExtractedEntity(
                    document_id=document.id,
                    page_number=h.page_number,
                    section_id=h.section_id,
                    entity_type=h.entity_type,
                    raw_text=h.raw_text[:490],
                    normalized_text=(h.normalized_text or None),
                    normalized_confidence=h.normalized_confidence,
                    source_snippet=h.source_snippet[:1000],
                    extraction_method="rule",
                ))
                entity_count += 1
            for mh in hits.measurements:
                db.add(models.Measurement(
                    document_id=document.id,
                    page_number=mh.page_number,
                    chunk_id=mh.chunk_id,
                    name=mh.name[:190],
                    value_raw=mh.value_raw[:90],
                    value_num=mh.value_num,
                    unit=mh.unit,
                    reference_range=(mh.reference_range[:90] if mh.reference_range else None),
                    flag=mh.flag,
                    source_snippet=mh.source_snippet,
                ))
                measurement_count += 1
        _model_run(db, "entities", "rules", ENTITY_EXTRACTOR_VERSION,
                  (time.perf_counter() - t_e) * 1000, document.id,
                  meta={"entities": entity_count, "measurements": measurement_count,
                        "version": ENTITY_EXTRACTOR_VERSION})

        # ---- Chunking ---------------------------------------------------------
        t_c = time.perf_counter()
        chunk_inputs: list[tuple] = []
        for sec in detected:
            sec_row = section_rows.get(sec.title)
            chunk_inputs.append(
                (sec_row.id if sec_row else None, sec.title, sec.page_number, sec.text, False)
            )
            # table chunks for tables on pages within this section
        for p in extracted.pages:
            for tab in p.tables:
                text = serialize_table(tab.header, tab.rows, tab.caption)
                if text.strip():
                    chunk_inputs.append((None, "Tables", p.page_number, text, True))
        result = chunk_document(chunk_inputs)
        for c in result.chunks:
            db.add(models.Chunk(
                document_id=document.id,
                section_id=c.section_id,
                page_number=c.page_number,
                chunk_index=c.chunk_index,
                text=c.text,
                char_count=c.char_count,
                token_estimate=c.token_estimate,
                is_table_chunk=c.is_table_chunk,
                embedding_model=settings.embedding_model,
            ))
        _model_run(db, "chunk", "rules", result.version,
                  (time.perf_counter() - t_c) * 1000, document.id,
                  meta={"chunks": len(result.chunks)})

        # ---- Doc-level fields ---------------------------------------------------
        date_ent = (
            db.query(models.ExtractedEntity)
            .filter(
                models.ExtractedEntity.document_id == document.id,
                models.ExtractedEntity.entity_type == "date",
                models.ExtractedEntity.normalized_confidence >= 0.9,
            )
            .order_by(models.ExtractedEntity.normalized_text)
            .first()
        )
        document.doc_date = date_ent.normalized_text if date_ent else None
        document.title = (title or document.original_filename)[:500]
        document.page_count = extracted.page_count
        document.word_count = extracted.word_count
        document.doc_type = extracted.doc_type
        document.status = "completed"
        document.status_message = None
        document.pipeline_version = PIPELINE_VERSION
        db.commit()

        # ---- Persist full extracted text ------------------------------------
        all_text = "\n\n".join(
            f"--- Page {p.page_number} ({p.extraction_method}) ---\n{p.text}"
            for p in extracted.pages
        )
        storage.save_extracted_text(document.id, all_text)

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "document processed doc_id=%s pages=%s chunks=%s entities=%s tables=%s ms=%d",
            document.id, extracted.page_count, len(result.chunks), entity_count,
            table_count, int(total_ms),
        )
        return document

    except Exception as e:
        db.rollback()
        document.status = "failed"
        document.status_message = str(e)[:900]
        db.commit()
        if isinstance(e, ProcessingError):
            log.warning("processing failed doc_id=%s reason=%s", document.id, e)
            raise
        log.error("processing crashed doc_id=%s err=%s: %s",
                  document.id, type(e).__name__, str(e)[:300])
        raise ProcessingError(f"Processing failed: {type(e).__name__}: {str(e)[:300]}") from e

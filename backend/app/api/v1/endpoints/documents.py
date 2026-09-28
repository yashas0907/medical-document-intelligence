from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.core.errors import (
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationError,
)
from app.db import models
from app.schemas.index import (
    DocumentOut,
    EntityOut,
    MeasurementOut,
    PageOut,
    ProcessingStatusOut,
    SectionOut,
    TableOut,
)
from app.services import auth_service, storage
from app.workers import runner

router = APIRouter()


def _get_owned_doc(db: Session, user, doc_id: str) -> models.Document:
    doc = db.get(models.Document, doc_id)
    if not doc:
        raise NotFoundError("Document not found", details={"document_id": doc_id})
    if doc.owner_id != user.id and user.role != "admin":
        raise ForbiddenError("You do not have access to this document")
    return doc


def _process_job(db_session_factory, doc_id: str, stored_path_str: str, ext: str) -> None:
    """Worker thread body: open own session, read file, run pipeline."""
    import pathlib

    from app.core.logging import get_logger

    log = get_logger("worker.job")
    db = db_session_factory()
    try:
        doc = db.get(models.Document, doc_id)
        if not doc:
            log.error("job: document vanished doc_id=%s", doc_id)
            return
        data = pathlib.Path(stored_path_str).read_bytes()
        from app.services.processing import process_document
        process_document(db, doc, data)
    except Exception as e:
        # process_document records failure state on the Document row for anything
        # raised inside the pipeline; this outer guard covers storage/IO errors.
        log.error("job crashed doc_id=%s err=%s: %s", doc_id, type(e).__name__, str(e)[:300])
        try:
            doc = db.get(models.Document, doc_id)
            if doc and doc.status != "failed":
                doc.status = "failed"
                doc.status_message = f"Job error: {type(e).__name__}: {str(e)[:400]}"
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    settings = get_settings()
    raw = await file.read()
    if len(raw) == 0:
        raise ValidationError("Uploaded file is empty")
    if len(raw) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"File exceeds {settings.max_upload_mb} MB limit",
            details={"size_bytes": len(raw), "limit_bytes": settings.max_upload_bytes},
        )

    original_name = storage.sanitize_filename(file.filename or "upload")
    ext = storage.extension_of(original_name)
    if not ext:
        raise ValidationError("File has no extension")
    storage.validate_extension(ext)

    sha = storage.sha256_bytes(raw)

    # duplicate detection for this user
    dup = db.scalar(
        select(models.Document).where(
            models.Document.owner_id == user.id, models.Document.sha256 == sha
        )
    )
    if dup:
        raise ValidationError(
            "This exact file was already uploaded",
            details={"existing_document_id": dup.id, "title": dup.title},
        )

    doc = models.Document(
        owner_id=user.id,
        title=original_name,
        original_filename=original_name,
        stored_filename="pending",  # set below after storage write
        content_type=file.content_type or "",
        file_size=len(raw),
        sha256=sha,
        status="uploaded",
    )
    db.add(doc)
    db.flush()
    stored = storage.save_original(doc.id, raw, ext)
    doc.stored_filename = stored
    db.commit()

    auth_service.audit(db, "upload", user_id=user.id, resource_type="document",
                       resource_id=doc.id, ip=request.client.host if request.client else None,
                       details={"size": len(raw), "ext": ext})

    # queue processing job
    from app.db.session import get_session_factory
    stored_path = str(storage.original_path(doc.id, stored))
    runner.submit(_process_job, get_session_factory(), doc.id, stored_path, ext)

    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return (
        db.scalars(
            select(models.Document)
            .where(models.Document.owner_id == user.id)
            .order_by(models.Document.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        .all()
    )


@router.get("/stats")
def document_stats(db: Session = Depends(get_db), user=Depends(get_current_user)):
    base = select(models.Document).where(models.Document.owner_id == user.id)
    docs = db.scalars(base).all()
    ids = [d.id for d in docs]
    if not ids:
        return {
            "documents": 0, "completed": 0, "processing": 0, "failed": 0,
            "pages": 0, "chunks": 0, "entities": 0, "measurements": 0,
            "qa_pairs": 0, "comparisons": 0,
        }

    def count(model, where):
        return db.scalar(select(func.count()).select_from(model).where(where)) or 0

    return {
        "documents": len(docs),
        "completed": sum(1 for d in docs if d.status == "completed"),
        "processing": sum(1 for d in docs if d.status in ("uploaded", "processing")),
        "failed": sum(1 for d in docs if d.status == "failed"),
        "pages": count(models.Page, models.Page.document_id.in_(ids)),
        "chunks": count(models.Chunk, models.Chunk.document_id.in_(ids)),
        "entities": count(models.ExtractedEntity, models.ExtractedEntity.document_id.in_(ids)),
        "measurements": count(models.Measurement, models.Measurement.document_id.in_(ids)),
        "qa_pairs": count(
            models.ChatMessage,
            models.ChatMessage.role == "user",
        ) // 2,
        "comparisons": count(models.ComparisonJob, models.ComparisonJob.user_id == user.id),
    }


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_owned_doc(db, user, document_id)


@router.delete("/{document_id}", status_code=204)
def delete_document(
    request: Request,
    document_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = _get_owned_doc(db, user, document_id)
    storage.delete_document_files(document_id)
    db.delete(doc)  # cascades pages/sections/chunks/entities/...
    db.commit()
    auth_service.audit(db, "delete", user_id=user.id, resource_type="document",
                       resource_id=document_id, ip=request.client.host if request.client else None)


@router.post("/{document_id}/process", response_model=DocumentOut, status_code=202)
def reprocess(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    doc = _get_owned_doc(db, user, document_id)
    if doc.status == "processing":
        raise ValidationError("Document is already being processed")
    path = storage.original_path(doc.id, doc.stored_filename)
    from app.db.session import get_session_factory
    runner.submit(_process_job, get_session_factory(), doc.id, str(path), storage.extension_of(doc.original_filename))
    doc.status = "processing"
    db.commit()
    return doc


@router.get("/{document_id}/status", response_model=ProcessingStatusOut)
def status(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    doc = _get_owned_doc(db, user, document_id)
    secs = db.scalars(
        select(models.Section).where(models.Section.document_id == doc.id)
    ).all()
    chunks = db.scalars(
        select(models.Chunk).where(models.Chunk.document_id == doc.id)
    ).all()
    ents = db.scalars(
        select(models.ExtractedEntity).where(models.ExtractedEntity.document_id == doc.id)
    ).all()
    meas = db.scalars(
        select(models.Measurement).where(models.Measurement.document_id == doc.id)
    ).all()
    tabs = db.scalars(
        select(models.TableExtraction).where(models.TableExtraction.document_id == doc.id)
    ).all()
    return ProcessingStatusOut(
        document_id=doc.id,
        status=doc.status,
        status_message=doc.status_message,
        page_count=doc.page_count,
        sections=len(secs),
        chunks=len(chunks),
        entities=len(ents),
        measurements=len(meas),
        tables=len(tabs),
        updated_at=doc.updated_at,
    )


@router.get("/{document_id}/sections", response_model=list[SectionOut])
def sections(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _get_owned_doc(db, user, document_id)
    return db.scalars(
        select(models.Section)
        .where(models.Section.document_id == document_id)
        .order_by(models.Section.order_index)
    ).all()


@router.get("/{document_id}/pages", response_model=list[PageOut])
def pages(
    document_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _get_owned_doc(db, user, document_id)
    return db.scalars(
        select(models.Page)
        .where(models.Page.document_id == document_id)
        .order_by(models.Page.page_number)
        .offset(skip)
        .limit(limit)
    ).all()


@router.get("/{document_id}/entities", response_model=list[EntityOut])
def entities(
    document_id: str,
    type: str | None = Query(None, description="Filter by entity type"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _get_owned_doc(db, user, document_id)
    q = select(models.ExtractedEntity).where(models.ExtractedEntity.document_id == document_id)
    if type:
        q = q.where(models.ExtractedEntity.entity_type == type)
    return db.scalars(
        q.order_by(models.ExtractedEntity.entity_type, models.ExtractedEntity.raw_text)
    ).all()


@router.get("/{document_id}/measurements", response_model=list[MeasurementOut])
def measurements(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _get_owned_doc(db, user, document_id)
    return db.scalars(
        select(models.Measurement).where(models.Measurement.document_id == document_id)
    ).all()


@router.get("/{document_id}/tables", response_model=list[TableOut])
def tables(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _get_owned_doc(db, user, document_id)
    return db.scalars(
        select(models.TableExtraction)
        .where(models.TableExtraction.document_id == document_id)
        .order_by(models.TableExtraction.table_index)
    ).all()


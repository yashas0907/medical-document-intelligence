from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.documents import _get_owned_doc
from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationError
from app.db import models
from app.schemas.index import (
    AskRequest,
    AskResult,
    ChatMessageOut,
    ContradictionsResult,
    ConversationOut,
    TimelineOut,
)
from app.services import auth_service, rag_service

router = APIRouter()


@router.post("/{document_id}/ask", response_model=AskResult)
async def ask_document(
    document_id: str,
    request: Request,
    payload: AskRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    settings = get_settings()
    if settings.rate_limit_ai_per_min > 0:
        # soft per-request accounting via ModelRun; hard limit enforced by slowapi on router-level in prod
        pass
    _get_owned_doc(db, user, document_id)
    doc_ids = payload.document_ids or [document_id]
    # authorization on extra docs
    for did in doc_ids:
        _get_owned_doc(db, user, did)
    for did in doc_ids:
        doc = db.get(models.Document, did)
        if doc and doc.status != "completed":
            raise ValidationError(
                f"Document {did} is not fully processed (status: {doc.status})"
            )
    result = rag_service.ask_documents(
        db, user, payload.question, doc_ids,
        conversation_id=payload.conversation_id,
    )
    auth_service.audit(db, "ask", user_id=user.id, resource_type="document",
                       resource_id=document_id,
                       ip=request.client.host if request.client else None)
    return AskResult(**result)


@router.get("/{document_id}/conversations", response_model=list[ConversationOut])
def conversations(
    document_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _get_owned_doc(db, user, document_id)
    return db.scalars(
        select(models.Conversation)
        .where(models.Conversation.user_id == user.id,
               models.Conversation.document_id == document_id)
        .order_by(models.Conversation.created_at.desc())
    ).all()


@router.get("/{document_id}/conversations/{conversation_id}/messages",
            response_model=list[ChatMessageOut])
def messages(
    document_id: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _get_owned_doc(db, user, document_id)
    conv = db.get(models.Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise NotFoundError("Conversation not found")
    return db.scalars(
        select(models.ChatMessage)
        .where(models.ChatMessage.conversation_id == conversation_id)
        .order_by(models.ChatMessage.created_at)
    ).all()


@router.get("/{document_id}/timeline", response_model=TimelineOut)
def timeline(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    doc = _get_owned_doc(db, user, document_id)
    from app.services import analysis_service
    return TimelineOut(**analysis_service.build_timeline(db, doc))


@router.get("/{document_id}/citations")
def citations(document_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _get_owned_doc(db, user, document_id)
    rows = db.scalars(
        select(models.Citation)
        .join(models.Document, models.Citation.document_id == models.Document.id)
        .where(models.Citation.document_id == document_id)
        .order_by(models.Citation.created_at.desc())
        .limit(500)
    ).all()
    return {
        "document_id": document_id,
        "citations": [
            {
                "id": c.id, "ref_label": c.ref_label, "page_number": c.page_number,
                "section_title": c.section_title, "quote": c.quote[:300],
                "chunk_id": c.chunk_id, "message_id": c.message_id,
                "created_at": c.created_at.isoformat(),
            }
            for c in rows
        ],
    }


@router.post("/{document_id}/contradictions", response_model=ContradictionsResult)
def contradictions(
    document_id: str,
    compare_with: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = _get_owned_doc(db, user, document_id)
    other = None
    if compare_with:
        other = _get_owned_doc(db, user, compare_with)
    from app.services import analysis_service
    result = analysis_service.run_contradictions(db, doc, other)
    return ContradictionsResult(**result)

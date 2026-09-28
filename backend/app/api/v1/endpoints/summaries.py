from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.documents import _get_owned_doc
from app.schemas.index import SummaryRequest, SummaryResult
from app.services import analysis_service

router = APIRouter()


@router.post("/{document_id}/summarize", response_model=SummaryResult)
def summarize(
    document_id: str,
    payload: SummaryRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = _get_owned_doc(db, user, document_id)
    if doc.status != "completed":
        from app.core.errors import ValidationError
        raise ValidationError(
            f"Document is not fully processed (status: {doc.status})"
        )
    result = analysis_service.build_summary(
        db, doc, payload.mode, payload.section_id, payload.max_words
    )
    return SummaryResult(**result)

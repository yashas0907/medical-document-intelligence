from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.documents import _get_owned_doc
from app.core.errors import ValidationError
from app.schemas.index import CompareRequest, ComparisonResultOut
from app.services import analysis_service

router = APIRouter()


@router.post("/documents/compare", response_model=ComparisonResultOut)
def compare(payload: CompareRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if payload.document_a_id == payload.document_b_id:
        raise ValidationError("Cannot compare a document with itself")
    a = _get_owned_doc(db, user, payload.document_a_id)
    b = _get_owned_doc(db, user, payload.document_b_id)
    for d in (a, b):
        if d.status != "completed":
            raise ValidationError(
                f"Document '{d.title}' is not fully processed (status: {d.status})"
            )
    result = analysis_service.run_comparison(db, user, a, b)
    return ComparisonResultOut(**result)

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import get_settings
from app.db import models
from app.services import storage

router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    settings = get_settings()
    db_ok = False
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    storage_ok = True
    try:
        storage.storage_root()
    except Exception:
        storage_ok = False
    return {
        "status": "ok" if db_ok and storage_ok else "degraded",
        "app": settings.app_name,
        "version": "1.0.0",
        "database": db_ok,
        "storage": storage_ok,
        "llm": {"enabled": settings.llm_enabled, "provider": settings.llm_provider,
                "model": settings.llm_model or ""},
        "ocr": {"provider": settings.ocr_provider},
        "time": datetime.now(UTC).isoformat(),
    }


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "role": user.role}


@router.get("/runs")
def model_runs(
    kind: str | None = None, limit: int = 50, db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    from sqlalchemy import select

    q = select(models.ModelRun).order_by(models.ModelRun.created_at.desc()).limit(min(limit, 200))
    if kind:
        q = q.where(models.ModelRun.kind == kind)
    rows = db.scalars(q).all()
    return [
        {
            "id": r.id, "kind": r.kind, "provider": r.provider, "model": r.model,
            "prompt_version": r.prompt_version, "pipeline_version": r.pipeline_version,
            "duration_ms": r.duration_ms, "success": r.success,
            "error_code": r.error_code, "meta": r.meta,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

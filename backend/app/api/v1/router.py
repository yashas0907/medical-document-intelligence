from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    comparisons,
    documents,
    misc,
    qa,
    summaries,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(qa.router, prefix="/documents", tags=["qa"])
api_router.include_router(summaries.router, prefix="/documents", tags=["summaries"])
api_router.include_router(comparisons.router, tags=["comparisons"])
api_router.include_router(misc.router, tags=["system"])

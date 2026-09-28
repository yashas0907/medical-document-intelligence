"""FastAPI application factory: routers, security, errors, rate limits, observability."""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.session import get_engine, get_session_factory
from app.workers.runner import shutdown_executor

log = get_logger("app")

VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    engine = get_engine()
    from app.db import models
    models.Base.metadata.create_all(bind=engine)  # dev convenience; prod uses Alembic
    sf = get_session_factory()
    with sf() as db:
        from app.services.auth_service import ensure_demo_user
        ensure_demo_user(db)
    log.info("startup complete app=%s env=%s db=%s", settings.app_name, settings.app_env, "sqlite" if "sqlite" in settings.database_url else "postgres")
    yield
    shutdown_executor()
    engine.dispose()
    log.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} — AI Medical Document Intelligence Platform",
        version=VERSION,
        description=(
            "Document intelligence for medical reports: ingestion, OCR, extraction, "
            "hybrid retrieval RAG with citations, comparison, timelines, and "
            "contradiction detection.\n\n**Not a medical device.** Informational "
            "document analysis only — not a substitute for professional medical judgment."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # rate limiter (per-IP; identity-scoped endpoints also check auth)
    limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limited",
                               "message": f"Rate limit exceeded: {exc.detail}",
                               "details": {}}},
        )

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error",
                              "message": "Invalid request payload",
                              "details": {"errors": exc.errors()[:10]}}},
        )

    @app.middleware("http")
    async def _timing_mw(request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            raise
        response.headers["X-Process-Time-Ms"] = str(int((time.perf_counter() - start) * 1000))
        return response

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()

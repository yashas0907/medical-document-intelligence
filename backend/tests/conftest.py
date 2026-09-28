"""Shared pytest fixtures: isolated DB (per-test tmp sqlite), test app, auth helpers."""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def temp_env(tmp_path, monkeypatch):
    """Isolated env: DB + storage under tmp_path."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-pytest-only")
    monkeypatch.setenv("APP_ENV", "dev")
    # CI runs many auth calls from a single IP; keep generous test limits
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_UPLOAD_PER_MIN", "1000")
    monkeypatch.setenv("RATE_LIMIT_AI_PER_MIN", "1000")
    # fresh settings + engine
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.db.session import reset_engine_for_tests

    reset_engine_for_tests()
    yield
    reset_engine_for_tests()
    get_settings.cache_clear()
    # clear retriever memo cache between tests
    from app.ml.retrieval import store

    if hasattr(store.get_document_retriever, "_cache"):
        store.get_document_retriever._cache = {}


@pytest.fixture()
def db(temp_env):
    from app.db import models
    from app.db.session import get_engine, get_session_factory

    engine = get_engine()
    models.Base.metadata.create_all(bind=engine)
    sf = get_session_factory()
    session = sf()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def user(db):
    from app.core.security import hash_password
    from app.db import models

    u = models.User(email="tester@example.com", hashed_password=hash_password("test-password-123"))
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def auth_headers(user):
    from app.services.auth_service import issue_token

    token = issue_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client(temp_env, db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


SAMPLE_LAB = """City General Hospital - Laboratory Report

Patient Information
Patient: J. Doe (fictional)
Referring Physician: Dr. Emily Carter

Laboratory Results
Hemoglobin: 13.2 g/dL [12.0-16.0]
WBC: 6.7 x10^9/L [4.0-11.0]
Glucose: 108 mg/dL [70-100] (H)
HbA1c: 6.4 % [4.0-5.6] (H)

Medications
Metformin 500 mg twice daily.
Lisinopril 10 mg once daily.

Assessment and Plan
Type 2 diabetes mellitus with HbA1c above target. Continue current medications.
BP 128/82 mmHg. Follow-up scheduled 2024-06-10.
"""


@pytest.fixture()
def processed_doc(db, user):
    """Document fully processed through the real pipeline."""
    from app.db import models
    from app.services.processing import process_document

    doc = models.Document(
        owner_id=user.id, title="lab1.txt", original_filename="lab1.txt",
        stored_filename="x.txt", content_type="text/plain",
        file_size=len(SAMPLE_LAB), sha256="testhash0001",
    )
    db.add(doc)
    db.commit()
    return process_document(db, doc, SAMPLE_LAB.encode())

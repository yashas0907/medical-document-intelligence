"""Seed demo data: create demo user and ingest all fixtures as that user.

Requires the backend app to be importable and a running DB (defaults ok).
Run from repo root: python scripts/seed_demo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import os  # noqa: E402

os.environ.setdefault("DATABASE_URL", "sqlite:///./backend/data/app.db")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
from app.core.security import hash_password  # noqa: E402
from app.db.session import get_engine, get_session_factory  # noqa: E402
from app.db import models  # noqa: E402
from app.services.processing import process_document  # noqa: E402
from sqlalchemy import select  # noqa: E402

FIXTURES = ROOT / "data" / "fixtures"


def main() -> None:
    engine = get_engine()
    models.Base.metadata.create_all(bind=engine)
    sf = get_session_factory()
    db = sf()
    s = get_settings()

    user = db.scalar(select(models.User).where(models.User.email == s.demo_user_email))
    if not user:
        user = models.User(
            email=s.demo_user_email,
            hashed_password=hash_password(s.demo_user_password),
        )
        db.add(user)
        db.commit()
    print(f"demo user ready: {user.email}")

    for f in sorted(FIXTURES.iterdir()):
        if f.suffix not in {".pdf", ".docx", ".txt"}:
            continue
        existing = db.scalar(
            select(models.Document).where(
                models.Document.owner_id == user.id,
                models.Document.original_filename == f.name,
            )
        )
        if existing:
            print(f"  skip (exists): {f.name}")
            continue
        doc = models.Document(
            owner_id=user.id,
            title=f.name,
            original_filename=f.name,
            stored_filename="seed",
            content_type="",
            file_size=f.stat().st_size,
            sha256=f"seed-{f.name}",
        )
        db.add(doc)
        db.commit()
        doc = process_document(db, doc, f.read_bytes())
        print(f"  ingested {f.name}: {doc.status} pages={doc.page_count}")
    db.close()
    engine.dispose()
    print("done")


if __name__ == "__main__":
    main()

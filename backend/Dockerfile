# Production image — build from the REPO ROOT (context: ".", file: backend/Dockerfile):
#   docker build -f backend/Dockerfile -t medintel .
#
# Boot sequence: Alembic migrations -> best-effort demo seed -> uvicorn (1 worker:
# the async job pool and retrieval cache are in-process by design).
FROM python:3.12-slim

# Tesseract OCR for scanned-page ingestion
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Backend code + configs
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app

# Scripts + synthetic demo fixtures (seeded at boot; idempotent)
COPY scripts /app/scripts
COPY data/fixtures /app/data/fixtures

# psycopg (Postgres driver) installs on Linux via its env marker in pyproject
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir bcrypt==4.1.3

EXPOSE 8000

ENV APP_ENV=prod \
    PYTHONUNBUFFERED=1

# Render injects $PORT. Seed is best-effort: on ephemeral free-tier disks the
# demo docs re-seed whenever the data is absent; a seed failure must never
# block the API from serving.
CMD ["sh", "-c", "python -m alembic upgrade head && (python ../scripts/seed_demo.py || echo 'WARN: demo seed failed (non-fatal)') && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

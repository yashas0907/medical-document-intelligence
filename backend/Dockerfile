FROM python:3.12-slim

# Tesseract OCR + runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY app ./app

RUN pip install --no-cache-dir -e . && pip install --no-cache-dir bcrypt==4.1.3

EXPOSE 8000

# Run migrations then start
CMD ["sh", "-c", "python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]

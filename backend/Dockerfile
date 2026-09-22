FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq for psycopg; gcc only for wheels that need building.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

# Never run the API as root.
RUN useradd --create-home --uid 10001 navigiq && chown -R navigiq /app
USER navigiq

EXPOSE 8000

# Migrations run before the server starts; they are idempotent. Several
# workers: the recommendation scoring is CPU-bound Python (see
# docs/reports/load_test.md: 4 workers ~2.4x the throughput of one).
ENV UVICORN_WORKERS=4
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS} --proxy-headers --forwarded-allow-ips='*'"]

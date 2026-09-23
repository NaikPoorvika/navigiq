FROM postgis/postgis:16-3.4

# NQ-003: pgvector for Phase 3 RAG embeddings
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

# NQ-003: extension creation, runs on first start with an empty data directory
COPY init/ /docker-entrypoint-initdb.d/

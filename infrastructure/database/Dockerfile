FROM postgis/postgis:16-3.4

# Update apt repositories and install pgvector
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

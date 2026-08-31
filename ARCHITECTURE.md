# NAVIGIQ ARCHITECTURE (ARCHITECTURE.md)

## 1. System Overview
NavigIQ is a controlled AI software application built as a Modular Monolith. It combines an advanced deterministic travel planner with bounded agentic AI capabilities, optimized for local inference on a single workstation.

## 2. Core Architectural Principles
- **The deterministic core is authoritative for travel planning.**
- **The LLM is an orchestration and language layer.**

## 3. Deployment
Single workstation architecture (Windows 64-bit / WSL2) using Docker and Docker Compose. No mandatory cloud APIs or multi-server deployments.

## 4. Architecture Diagram
```text
+-------------------------------------------------------------+
|                          USER INTERFACE                     |
|  (Frontend: React, Vite, Leaflet, PWA)                      |
+-------------------------------------------------------------+
                              |
+-------------------------------------------------------------+
|                          BACKEND API                        |
|  (Python, FastAPI, SQLAlchemy)                              |
+-------------------------------------------------------------+
     |                  |                   |              |
+---------+      +-------------+      +-----------+   +----------+
|  LLM    |      | DETERMINISTIC|      |   DATA    |   | LIVE     |
| (Ollama)|      | PLANNER      |      | (PostGIS) |   | EVENT    |
+---------+      +-------------+      +-----------+   +----------+
```

## 5. Components
- **Frontend**: React, Vite, Leaflet, PWA.
- **Backend**: Python, FastAPI, SQLAlchemy, Alembic.
- **Database**: PostgreSQL with PostGIS and pgvector for RAG.
- **Deterministic Planner**:
  - **Routing**: OSRM (authoritative for distances/ETAs).
  - **Optimization**: OR-Tools (authoritative for feasibility/constraints).
- **AI & LLM**:
  - **LLM**: Ollama for local inference.
  - **RAG**: PostgreSQL FTS, pgvector, hybrid retrieval, RRF.
  - **Agentic AI**: Bounded typed tools orchestration.
- **Live Event System**: Background processing via Celery and Redis.
- **Security Boundaries**: All AI actions pass through typed API boundaries. No arbitrary SQL/shell access.

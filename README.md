# NavigIQ

## Project Purpose
NavigIQ is a highly controlled, single-workstation agentic AI software engineering project designed to serve as an intelligent, robust, and verifiable travel planning application. 

## Current Status
- **Current Phase:** Phase 1 — Deterministic Planner (11 of 16 tasks)
- **Completed:** NQ-011 to NQ-021
- **Current Task:** NQ-022 — Feasibility engine
- **Data:** 14,851 POIs loaded from OpenStreetMap

## Architecture Summary
NavigIQ operates as a **Modular Monolith** built on a single-workstation architecture. It strictly divides logic between a **Deterministic Planner** (authoritative for routing, optimization, and spatial operations) and an **LLM** (acting as an orchestration and language layer via typed tools).

## Hardware Constraints
- CPU: Intel Xeon W-2295 @ 3.00 GHz (18 cores / 36 threads)
- RAM: 128 GB
- GPU: NVIDIA RTX A5000 (24 GB VRAM)
- Storage: 1.4 TB
- OS: Windows 64-bit (WSL2 supported)

## Prerequisites
- Node.js & npm (for React/Vite)
- Python 3.10+
- Docker & Docker Compose
- Git
- Ollama (for local inference)

## Repository Structure
- `/frontend`: React, Vite, Leaflet application.
- `/backend`: Python FastAPI and SQLAlchemy backend.
- `/ai`: Local LLM orchestration, prompts, and tooling.
- `/data`: Database migrations, vector storage setup.
- `/scripts`: Utility scripts for project setup and maintenance.
- `/infrastructure`: Docker and environment configuration.
- `/tests`: Project-wide testing suites.
- `/docs`: Additional architecture and setup documentation.

## Development Instructions
Development operates under strict, task-based approval gates. Ensure you review `CLAUDE.md` and `TASKS.md` for rules and current project status before proceeding.


## What NavigIQ does not do

Stated explicitly so nothing is implied that isn't supported:

- **No live traffic.** Travel times come from free-flow routing adjusted by a
  static time-of-day table. They are estimates and are labelled as such.
- **No public transit.** Metro was built and removed (ADR-007) after losing
  every route comparison. Bus routing is not implemented.
- **No real-time fares.** Auto and cab costs are formula-based estimates from
  published fare structures, not live pricing.
- **No POI ratings.** No lawful free source exists. Ranking uses a
  documentation-based prominence score (ADR-008); star ratings are never shown.
- **Opening hours are sparse.** Only 8.7% of POIs carry real hours from
  OpenStreetMap. The rest use category defaults at low confidence.

## Data attribution

POI and map data © OpenStreetMap contributors, licensed under ODbL.
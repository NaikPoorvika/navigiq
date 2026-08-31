# NavigIQ

## Project Purpose
NavigIQ is a highly controlled, single-workstation agentic AI software engineering project designed to serve as an intelligent, robust, and verifiable travel planning application. 

## Current Status
- **Current Phase:** Phase 0 — Foundation
- **Current Task:** NQ-003 — PostgreSQL + PostGIS + pgvector (Completed)

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

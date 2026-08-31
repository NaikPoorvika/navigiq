# NAVIGIQ ARCHITECTURAL DECISION RECORDS (DECISIONS.md)

## ADR-001: Single Workstation
**Status:** Accepted
**Decision:** The application is designed for ONE physical workstation (Intel Xeon W-2295, 128GB RAM, RTX A5000 24GB). Cloud APIs or distributed GPU setups will not be used.

## ADR-002: LLM is not authoritative
**Status:** Accepted
**Decision:** The LLM will only be used for orchestration, reasoning, and language generation. It is NOT the source of truth for coordinates, distances, routing, or budget calculations.

## ADR-003: Bounded Agentic AI
**Status:** Accepted
**Decision:** Agentic behavior is restricted. The agent must use strict typed tools to interact with deterministic services and must never execute arbitrary shell commands or SQL.

## ADR-004: Typed tool registry
**Status:** Accepted
**Decision:** All agentic capabilities will be exposed through a controlled registry of typed tools, preventing the fabrication of external requests or data.

## ADR-005: Deterministic planning core
**Status:** Accepted
**Decision:** All math, routing (OSRM), optimization (OR-Tools), and constraint validations are handled strictly by deterministic code, acting as the authoritative planner.

## ADR-006: Prefer modular monolith
**Status:** Accepted
**Decision:** The system will be built as a modular monolith. Separate containers are acceptable only where operationally justified (e.g., PostgreSQL, Redis, OSRM, Ollama), avoiding unnecessary microservices.

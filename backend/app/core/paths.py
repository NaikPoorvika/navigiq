"""Filesystem locations shared by the app, the ingestion pipeline and tests.

The repository keeps configuration and mappings under <repo>/data. Inside the
backend container the repository layout does not exist (only backend/ is
mounted at /app), so the location is overridable with NAVIGIQ_DATA_DIR and
docker-compose mounts ../data at /data.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    override = os.environ.get("NAVIGIQ_DATA_DIR")
    return Path(override) if override else REPO_ROOT / "data"


def config_path(name: str) -> Path:
    return data_dir() / "config" / name


def artifacts_dir() -> Path:
    path = data_dir() / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path

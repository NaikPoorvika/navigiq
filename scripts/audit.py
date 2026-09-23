"""Project health check. Run from the repo root with the venv active."""
import importlib
import subprocess
import sys


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


section("GIT")
print(run("git branch --show-current"))
print(run("git status --short") or "(clean)")
print(run("git fetch origin -q && git rev-list --left-right --count HEAD...origin/develop"),
      "  <- ahead / behind origin/develop")
print(run("git log --oneline -5"))

section("DOCKER")
print(run('docker ps --format "{{.Names}}: {{.Status}}"'))

section("SERVICES")
print("postgres:", run('docker exec navigiq_db psql -U navigiq -d navigiq -tAc '
                       '"SELECT count(*) FROM pois"'), "pois")
print("places:  ", run('docker exec navigiq_db psql -U navigiq -d navigiq -tAc '
                       '"SELECT count(*) FROM places"'))
print("categories:", run('docker exec navigiq_db psql -U navigiq -d navigiq -tAc '
                         '"SELECT count(*) FROM poi_categories"'))
print("osrm-car:", run('curl.exe -s "http://localhost:5000/route/v1/driving/'
                       '77.6408,12.9784;77.5946,12.9716?overview=false"')[:40])
print("osrm-foot:", run('curl.exe -s "http://localhost:5001/route/v1/foot/'
                        '77.6408,12.9784;77.6350,12.9760?overview=false"')[:40])

section("ALEMBIC")
print(run("cd backend && alembic heads"))
print(run("cd backend && alembic current"))

section("THIRD-PARTY IMPORTS vs requirements.txt")
modules = {
    "fastapi": "fastapi", "sqlalchemy": "sqlalchemy", "asyncpg": "asyncpg",
    "alembic": "alembic", "pydantic": "pydantic", "httpx": "httpx",
    "yaml": "PyYAML", "osmium": "osmium", "geoalchemy2": "geoalchemy2",
    "psycopg": "psycopg", "ortools": "ortools", "redis": "redis",
    "structlog": "structlog", "tzdata": "tzdata",
}
reqs = open("backend/requirements.txt", encoding="utf-8").read().lower()
for mod, pkg in modules.items():
    try:
        importlib.import_module(mod)
        installed = "installed"
    except ImportError:
        installed = "NOT INSTALLED"
    listed = "listed" if pkg.lower() in reqs else "MISSING FROM requirements.txt"
    print(f"  {pkg:<14} {installed:<14} {listed}")

section("TESTS")
print(run("cd backend && python -m pytest tests -q --tb=line")[-600:])
print(run("python -m pytest data/pipelines/test_osm_extract.py -q")[-200:])
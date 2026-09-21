"""Stage 12 - REPORT: data-quality metrics for the loaded inventory (section 33).

Computed from the database (not the pipeline's memory), so the report
describes what users will actually be served. Written as JSON for machines
and Markdown for reviewers (docs/data_quality_report.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from app.core.paths import REPO_ROOT, artifacts_dir


def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 1) if total else 0.0


def build_report(dsn: str, manifest: dict | None = None) -> dict:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        def one(sql: str, *args):
            cur.execute(sql, args)
            return cur.fetchone()[0]

        def rows(sql: str, *args):
            cur.execute(sql, args)
            return cur.fetchall()

        total = one("SELECT count(*) FROM pois WHERE active")
        rep = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_active_pois": total,
            "inactive_pois": one("SELECT count(*) FROM pois WHERE NOT active"),
            "recommendable_pois": one("SELECT count(*) FROM pois WHERE active AND recommendable"),
            "curated_pois": one("SELECT count(*) FROM pois WHERE active AND curated"),
            "by_category": dict(rows("""SELECT c.key, count(*) FROM pois p JOIN poi_categories c
                ON c.id = p.primary_category WHERE p.active GROUP BY 1 ORDER BY 2 DESC""")),
            "by_region_bucket": dict(rows("""SELECT region_bucket, count(*) FROM pois
                WHERE active GROUP BY 1 ORDER BY 1""")),
            "by_distance_band_km": dict(rows("""SELECT (floor(distance_from_center_km / 10) * 10)
                ::int || '-' || ((floor(distance_from_center_km / 10) + 1) * 10)::int, count(*)
                FROM pois WHERE active GROUP BY floor(distance_from_center_km / 10)
                ORDER BY floor(distance_from_center_km / 10)""")),
            "by_district": dict(rows("""SELECT coalesce(district, '(unknown)'), count(*)
                FROM pois WHERE active GROUP BY 1 ORDER BY 2 DESC""")),
            "top_localities": dict(rows("""SELECT coalesce(locality, '(unknown)'), count(*)
                FROM pois WHERE active GROUP BY 1 ORDER BY 2 DESC LIMIT 25""")),
            "coverage_pct": {
                "description": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                        "coalesce(short_description, description) IS NOT NULL"), total),
                "wikipedia_description": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                                  "description_source = 'wikipedia'"), total),
                "opening_hours_reliable": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                                   "opening_hours_confidence >= 0.5"), total),
                "opening_hours_any_source_tag": _pct(one("SELECT count(*) FROM pois WHERE active "
                                                         "AND opening_hours_raw IS NOT NULL"), total),
                "cost_non_default": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                             "cost_confidence <> 'category_default'"), total),
                "experience_tags": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                            "cardinality(experience_tags) > 0"), total),
                "mood_tags": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                      "cardinality(mood_tags) > 0"), total),
                "source_url": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                       "cardinality(source_urls) > 0"), total),
                "license": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                    "source_license <> ''"), total),
                "locality": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                     "locality IS NOT NULL"), total),
                "district": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                     "district IS NOT NULL"), total),
                "wikidata": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                     "wikidata_id IS NOT NULL"), total),
                "free_image": _pct(one("SELECT count(*) FROM pois WHERE active AND "
                                       "image_url IS NOT NULL"), total),
            },
            "opening_hours_confidence": dict(rows("""SELECT opening_hours_confidence::text,
                count(*) FROM pois WHERE active GROUP BY 1 ORDER BY 1""")),
            "cost_confidence": dict(rows("""SELECT cost_confidence, count(*) FROM pois
                WHERE active GROUP BY 1 ORDER BY 2 DESC""")),
            "chain_branches": one("SELECT count(*) FROM pois WHERE active AND is_chain"),
            "duplicate_candidates": one("""SELECT count(*) FROM pois a JOIN pois b
                ON a.id < b.id AND a.name_normalized = b.name_normalized
                AND ST_DWithin(a.geom, b.geom, 150) WHERE a.active AND b.active"""),
            "missing_coordinates": one("SELECT count(*) FROM pois WHERE geom IS NULL"),
            "outside_envelope": one("SELECT count(*) FROM pois WHERE active AND "
                                    "distance_from_center_km > 90.0"),
            "invalid_records": {
                "cost_order": one("SELECT count(*) FROM pois WHERE NOT (estimated_cost_min <= "
                                  "estimated_cost_typical AND estimated_cost_typical <= "
                                  "estimated_cost_max)"),
                "duration_order": one("SELECT count(*) FROM pois WHERE NOT (visit_duration_min "
                                      "<= visit_duration_typical AND visit_duration_typical <= "
                                      "visit_duration_max)"),
                "hours_interval": one("SELECT count(*) FROM poi_opening_hours WHERE "
                                      "close_min <= open_min AND NOT closed_all_day"),
            },
            "coverage_by_region": {
                b: {"total": t, "recommendable": rc, "with_description": dc}
                for b, t, rc, dc in rows("""SELECT region_bucket, count(*),
                    count(*) FILTER (WHERE recommendable),
                    count(*) FILTER (WHERE coalesce(short_description, description) IS NOT NULL)
                    FROM pois WHERE active GROUP BY 1 ORDER BY 1""")
            },
            "places": {
                "total": one("SELECT count(*) FROM places"),
                "by_type": dict(rows("SELECT place_type, count(*) FROM places GROUP BY 1 "
                                     "ORDER BY 2 DESC")),
            },
        }
    if manifest:
        rep["pipeline_manifest"] = manifest
    return rep


def write_report(rep: dict) -> tuple[Path, Path]:
    out_dir = artifacts_dir() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "data_quality_report.json"
    json_path.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str),
                         encoding="utf-8")
    md_path = REPO_ROOT / "docs" / "data_quality_report.md"
    md_path.write_text(to_markdown(rep), encoding="utf-8")
    return json_path, md_path


def to_markdown(rep: dict) -> str:
    lines = [
        "# NavigIQ POI data-quality report",
        "",
        f"Generated {rep['generated_at']} from the loaded database by "
        "`python -m app.ingestion.run --report-only`. Regenerate after every ingestion.",
        "",
        "Scores are documentation/notability measures, never ratings (ADR-008).",
        "",
        "## Totals",
        "",
        f"- Active POIs: **{rep['total_active_pois']:,}**",
        f"- Recommendable (quality-gated discovery pool): **{rep['recommendable_pois']:,}**",
        f"- Curated by NavigIQ: **{rep['curated_pois']:,}**",
        f"- Inactive (kept for history, never served): {rep['inactive_pois']:,}",
        f"- Chain branches: {rep['chain_branches']:,}",
        f"- Duplicate candidates (same name within 150 m): {rep['duplicate_candidates']}",
        f"- Missing coordinates: {rep['missing_coordinates']} · outside 90 km: "
        f"{rep['outside_envelope']}",
        f"- Invalid records: {rep['invalid_records']}",
        "",
        "## Coverage",
        "",
        "| Field | Coverage |",
        "|---|---|",
    ]
    lines += [f"| {k.replace('_', ' ')} | {v}% |" for k, v in rep["coverage_pct"].items()]
    lines += ["", "## By region", "", "| Region | POIs | Recommendable | With description |",
              "|---|---|---|---|"]
    lines += [f"| {b} | {v['total']:,} | {v['recommendable']:,} | {v['with_description']:,} |"
              for b, v in rep["coverage_by_region"].items()]
    lines += ["", "## By distance band (km from centre)", "", "| Band | POIs |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in rep["by_distance_band_km"].items()]
    lines += ["", "## By category", "", "| Category | POIs |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in rep["by_category"].items()]
    lines += ["", "## By district", "", "| District | POIs |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in rep["by_district"].items()]
    lines += ["", "## Top localities", "", "| Locality | POIs |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in rep["top_localities"].items()]
    lines += ["", "## Opening-hours confidence", "", "| Confidence | POIs |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in rep["opening_hours_confidence"].items()]
    lines += ["", "## Cost confidence", "", "| Basis | POIs |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in rep["cost_confidence"].items()]
    if rep.get("pipeline_manifest"):
        lines += ["", "## Pipeline manifest", "", "```json",
                  json.dumps(rep["pipeline_manifest"], indent=2, default=str), "```"]
    lines += ["", "Data © OpenStreetMap contributors (ODbL); Wikipedia text CC BY-SA 4.0; "
              "Wikidata CC0.", ""]
    return "\n".join(lines)

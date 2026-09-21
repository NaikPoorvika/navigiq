"""Stage 4 - CATEGORIZE: OSM tags -> taxonomy v2 via ordered YAML rules.

First match wins. A record that matches no rule, or matches a rule whose
requirements it fails, is dropped with a recorded reason - the manifest
counts every reason so the drop list stays reviewable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.core.paths import data_dir
from app.domain.taxonomy import category_catalog, is_valid_tag


@dataclass(frozen=True)
class Rule:
    index: int
    match: tuple[tuple[str, object], ...]
    category: str
    name_regex: re.Pattern | None = None
    requires: tuple[str, ...] = ()
    min_extent_m: float | None = None
    secondary: tuple[tuple[str, float], ...] = ()
    tags: tuple[str, ...] = ()


@dataclass
class MappingResult:
    category: str | None
    rule_index: int | None = None
    secondary: list[tuple[str, float]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    drop_reason: str | None = None


def is_notable(tags: dict) -> bool:
    return bool(tags.get("wikidata") or tags.get("wikipedia") or tags.get("tourism")
                or tags.get("heritage"))


def _value_matches(actual: str | None, expected: object) -> bool:
    if actual is None:
        return False
    if expected == "*":
        return True
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


class OSMMapping:
    def __init__(self, path: Path | None = None) -> None:
        path = path or (data_dir() / "mappings" / "osm_categories.yaml")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw.get("version") != 2:
            raise ValueError("osm_categories.yaml must be version 2")
        catalog = category_catalog()
        rules = []
        for i, r in enumerate(raw["rules"]):
            cat = r["category"]
            if cat not in catalog or catalog[cat].theme:
                raise ValueError(f"rule {i}: {cat!r} is not a valid primary category")
            for s in r.get("secondary", []):
                if s["category"] not in catalog:
                    raise ValueError(f"rule {i}: unknown secondary {s['category']!r}")
                if not 0 < float(s["weight"]) <= 1:
                    raise ValueError(f"rule {i}: secondary weight out of range")
            for t in r.get("tags", []):
                if not is_valid_tag(t):
                    raise ValueError(f"rule {i}: unknown tag {t!r}")
            for req in r.get("requires", []):
                if req not in ("name", "wikidata", "notable"):
                    raise ValueError(f"rule {i}: unknown requirement {req!r}")
            rules.append(Rule(
                index=i,
                match=tuple(sorted(r["match"].items())),
                category=cat,
                name_regex=re.compile(r["name_regex"], re.IGNORECASE) if r.get("name_regex") else None,
                requires=tuple(r.get("requires", [])),
                min_extent_m=r.get("min_extent_m"),
                secondary=tuple((s["category"], float(s["weight"])) for s in r.get("secondary", [])),
                tags=tuple(r.get("tags", [])),
            ))
        self.rules = rules
        self.gazetteer_place_types = tuple(raw.get("gazetteer_place_types", []))

    def resolve(self, tags: dict, name: str | None, extent_m: float | None,
                osm_type: str) -> MappingResult:
        if not name or not name.strip():
            # Every NavigIQ place has a name; an unnamed feature cannot be
            # searched for, cited or shown on a card.
            return MappingResult(None, None, drop_reason="missing_name")
        for rule in self.rules:
            if not all(_value_matches(tags.get(k), v) for k, v in rule.match):
                continue
            if rule.name_regex and not (name and rule.name_regex.search(name)):
                continue
            # First structural match decides; requirements then accept or drop.
            if "name" in rule.requires and not name:
                return MappingResult(None, rule.index, drop_reason="missing_name")
            if "wikidata" in rule.requires and not tags.get("wikidata"):
                return MappingResult(None, rule.index, drop_reason="missing_wikidata")
            if "notable" in rule.requires and not is_notable(tags):
                return MappingResult(None, rule.index, drop_reason="not_notable")
            if rule.min_extent_m is not None:
                if osm_type == "node":
                    if not tags.get("wikidata"):
                        return MappingResult(None, rule.index, drop_reason="node_without_extent")
                elif (extent_m or 0) < rule.min_extent_m and not tags.get("wikidata"):
                    return MappingResult(None, rule.index, drop_reason="below_min_extent")
            return MappingResult(
                category=rule.category, rule_index=rule.index,
                secondary=[s for s in rule.secondary if s[0] != rule.category],
                tags=list(rule.tags),
            )
        return MappingResult(None, None, drop_reason="unmapped")


@lru_cache(maxsize=1)
def default_mapping() -> OSMMapping:
    return OSMMapping()


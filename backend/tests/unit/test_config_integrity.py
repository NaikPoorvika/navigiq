"""Every controlled vocabulary and config file agrees with the code.

A drift here is silent in production (a category the DB has never heard of
matches nothing), so it fails loudly here instead.
"""
from __future__ import annotations

import math

from app.domain.taxonomy import (
    MOOD_DEFINITIONS, Category, ExperienceTag, Mood, category_catalog, is_valid_category,
    is_valid_tag, moods_for,
)
from app.ingestion.mapping import default_mapping
from app.llm.prompts import VOCABULARY
from app.nlu.lexicon import lexicon
from app.services.collections import definitions
from app.services.recommendation.scoring import config as rec_config


def test_category_yaml_matches_enum_exactly():
    assert set(category_catalog()) == {c.value for c in Category}


def test_category_ranges_are_ordered():
    for c in category_catalog().values():
        assert 0 < c.duration[0] <= c.duration[1] <= c.duration[2]
        assert 0 <= c.cost[0] <= c.cost[1] <= c.cost[2]


def test_theme_categories_are_never_primary_in_mapping():
    catalog = category_catalog()
    for rule in default_mapping().rules:
        assert not catalog[rule.category].theme


def test_mood_definitions_use_controlled_values():
    assert set(MOOD_DEFINITIONS) == set(Mood)
    for d in MOOD_DEFINITIONS.values():
        assert all(is_valid_tag(t) for t in d["tags"])
        assert all(is_valid_category(c) for c in d["categories"])


def test_moods_require_evidence_beyond_category():
    assert "peaceful" not in moods_for(set(), "park")
    assert "peaceful" in moods_for({"peaceful"}, "park")
    assert "romantic" in moods_for({"romantic"}, "other")


def test_lexicon_loads_and_is_controlled():
    lex = lexicon()
    assert len(lex.entries) > 300
    assert lex.negators and lex.postfix_negators


def test_recommendation_weights_sum_to_one():
    assert math.isclose(sum(rec_config()["weights"].values()), 1.0, abs_tol=1e-9)


def test_collections_are_query_definitions_not_poi_lists():
    for c in definitions():
        assert "poi_ids" not in c and "pois" not in c
        assert c["title"]


def test_llm_vocabulary_is_exactly_the_controlled_set():
    expected = {c.value for c in Category} | {t.value for t in ExperienceTag} | {
        m.value for m in Mood}
    assert set(VOCABULARY) == expected

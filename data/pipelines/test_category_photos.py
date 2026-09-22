"""Offline tests for deriving category photos from photographed POIs."""
from __future__ import annotations

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from category_photos import Photographed, choose  # noqa: E402


def row(cat, poi_id, links):
    return Photographed(cat, poi_id, f"Place {poi_id}", f"https://x/{poi_id}.jpg",
                        "Author", "CC BY-SA 4.0", "https://src", links)


def test_picks_most_notable_place_in_each_category():
    chosen = choose([row("lake", 1, 5), row("lake", 2, 40)])
    assert chosen["lake"].poi_id == 2


def test_never_reuses_a_place():
    chosen = choose([row("park", 1, 50), row("landmark", 1, 50), row("landmark", 2, 10)])
    ids = [r.poi_id for r in chosen.values()]
    assert len(ids) == len(set(ids))


def test_scarce_category_chooses_first():
    """Place 1 is the only lake. 'landmark' has others, so it must not take it."""
    rows = [row("lake", 1, 30), row("landmark", 1, 30), row("landmark", 2, 99)]
    chosen = choose(rows)
    assert chosen["lake"].poi_id == 1
    assert chosen["landmark"].poi_id == 2


def test_category_without_photos_is_absent():
    assert "cafe" not in choose([row("lake", 1, 5)])


# ------------------------------------------ reading the real schema

from category_photos import category_sql  # noqa: E402


def test_numeric_category_id_is_joined_to_its_key():
    """The bug from the first real run: ids 12 and 16 were saved as keys."""
    select, join = category_sql({"poi_id": "integer", "category_id": "integer"},
                                {"id", "key", "display_name"})
    assert select == "c.key"
    assert "c.id = l.category_id" in join


def test_text_category_key_is_used_directly():
    select, join = category_sql({"poi_id": "integer", "category_key": "character varying"},
                                {"key", "display_name"})
    assert select == "l.category_key" and join == ""


# ------------------------------------------ search fallback for missing ones

from category_photos import photo_subject, pick_search_result  # noqa: E402


def cand(title, mime="image/jpeg", width=1200, license="CC BY-SA 4.0"):
    return {"title": title, "url": "u", "width": width, "mime": mime,
            "license": license, "credit": "A", "source": "s"}


def test_search_skips_logos_small_and_non_free():
    pick = pick_search_result([
        cand("File:Cafe Coffee Day logo.png"),
        cand("File:Tiny cafe.jpg", width=200),
        cand("File:Cafe copyrighted.jpg", license="All rights reserved"),
        cand("File:Cafe in Indiranagar.jpg"),
    ])
    assert pick and pick["title"] == "File:Cafe in Indiranagar.jpg"


def test_search_returns_none_when_nothing_suitable():
    assert pick_search_result([cand("File:Bar chart.png")]) is None


def test_photo_subject_is_readable():
    assert photo_subject("File:Cafe_in_Indiranagar_2019.jpg") == "Cafe in Indiranagar 2019"


# ------------------------------------------ a failed search must not lose the rest

from category_photos import search_missing  # noqa: E402


class Refused(Exception):
    class response:  # noqa: N801
        status_code = 403


def test_refusal_stops_searching_but_keeps_what_was_found():
    calls = []

    def search(client, name, key=None):
        calls.append(name)
        if name == "Bar":
            raise Refused()
        return cand(f"File:{name} in Bangalore.jpg")

    found = search_missing(None, ["bar", "cafe", "dessert"],
                           {"bar": "Bar", "cafe": "Cafe", "dessert": "Dessert"}, search)
    assert found == {}                 # refused on the first - nothing searched after
    assert calls == ["Bar"]


def test_other_failures_skip_only_that_category():
    def search(client, name, key=None):
        if name == "Bar":
            raise TimeoutError()
        return cand(f"File:{name} in Bangalore.jpg")

    found = search_missing(None, ["bar", "cafe"], {"bar": "Bar", "cafe": "Cafe"}, search)
    assert list(found) == ["cafe"]



# ------------------------------------- the subject must be named, as a word

from category_photos import names_the_subject  # noqa: E402


@pytest.mark.parametrize("title,term", [
    ("BarCamp Bangalore 002", "Bar"),               # the real wrong result
    ("Market-bangalore-2", "Bookstore"),            # the real wrong result
])
def test_titles_that_dont_name_the_subject_are_rejected(title, term):
    assert not names_the_subject(title, term)


@pytest.mark.parametrize("title,term", [
    ("Hard Rock Cafe, Bangalore", "Cafe"),
    ("Dessert Works Bangalore", "Dessert"),
    ("Avarebele Dose - VV Puram Food Street, Bangalore", "Street Food"),
    ("'Brigade Road ,Bangalore' at Night", "night"),
    ("Blossom Bookshops, Church Street", "bookshop"),
])
def test_titles_that_name_the_subject_are_kept(title, term):
    assert names_the_subject(title, term)


def test_barcamp_is_skipped_for_a_real_pub():
    pick = pick_search_result([cand("File:BarCamp Bangalore 002.jpg"),
                               cand("File:Pub on Church Street.jpg")], "pub")
    assert pick and "Pub" in pick["title"]

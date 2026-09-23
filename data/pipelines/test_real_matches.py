"""Every match from the first real dry run (85 rows), as a regression test.

The four rows in WRONG were reviewed by hand and are not the same place.
Every other row was reviewed and IS the same place, and must stay matched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from wikidata_enrich import rejects  # noqa: E402

WRONG = [
    ("rajarajeshwari temple", "Rajarajeshwari Nagar"),
    ("seasons electronic city", "Electronic City metro station"),
    ("bangalore fort", "Fort Church, Bangalore"),
    ("begur inscription stone", "Inscription Stones of Bengaluru"),
]

RIGHT = [
    ("lalbagh botanical gardens", "Lalbagh Botanical Garden, Bangalore"),
    ("savanadurga", "Savandurga"),
    ("cubbon park", "Cubbon Park"),
    ("naganatheshwara temple", "Nageshvara Temple"),
    ("dharmaraya swamy temple", "Dharmaraya Swamy Temple"),
    ("st. francis xavier's cathedral", "St. Francis Xavier's Cathedral, Bengaluru"),
    ("halasuru lake", "Ulsoor Lake"),
    ("dodda ganesha temple", "Dodda Ganeshana Gudi"),
    ("tippu's summer palace", "Tipu Sultan's Summer Palace"),
    ("vidhana soudha", "Vidhana Soudha"),
    ("someshwara temple", "Halasuru Someshwara Temple, Bangalore"),
    ("st mary's basilica", "St. Mary's Basilica, Bangalore"),
    ("karnataka government museum", "Government Museum, Bengaluru"),
    ("bhoga nandeeshwara temple", "Bhoga Nandeeshwara Temple"),
    ("karnataka chitrakala parishath", "Karnataka Chitrakala Parishath College of Fine Arts"),
    ("mavalli tiffin rooms", "Mavalli Tiffin Room"),
    ("freedom park", "Freedom Park, Bangalore"),
    ("sri gavigangadhareshwara swamy temple", "Gavi Gangadhareshwara Temple"),
    ("hebbal lake", "Hebbal lake"),
    ("muthyala maduvu", "Muthyalamaduvu"),
    ("madiwala lake", "Madiwala Lake"),
    ("visvesvaraya industrial and technology museum", "Visvesvaraya Industrial and Technological Museum"),
    ("bangalore world trade center", "World Trade Center, Bengaluru"),
    ("sri chandra choodeswarar temple", "Chandra Choodeswarar Temple, Hosur"),
    ("kempegowda museum", "Kempegowda Museum"),
    ("sankey tank", "Sankey tank"),
    ("dodda alada mara", "Dodda Alada Mara"),
    ("national gallery of modern art", "National Gallery of Modern Art, Bengaluru"),
    ("puttenhalli lake", "Puttenahalli Lake"),
    ("gandhi bhavan", "Gandhi Bhavan, Bengaluru"),
    ("garuda mall", "Garuda Mall"),
    ("hal aerospace museum", "HAL Aerospace Museum"),
    ("ranga shankara", "Ranga Shankara"),
    ("infant jesus church", "Infant Jesus Church, Bangalore"),
    ("orion mall", "Orion Malls"),
    ("venkatappa art gallery", "Venkatappa Art Gallery"),
    ("jakkur lake", "Jakkur Lake"),
    ("museum of art and photography", "Museum of Art & Photography"),
    ("jawaharlal nehru planetarium", "Jawaharlal Nehru Planetarium, Bengaluru"),
    ("queen victoria", "Statue of Queen Victoria"),
    ("phoenix market city", "Phoenix Marketcity Bangalore"),
    ("nexus koramangala", "Nexus Koramangala"),
    ("mantri square", "Mantri Square"),
    ("national military memorial", "National Military Memorial"),
    ("betarayara swami temple", "Betrayaswamy Temple"),
    ("st. andrews church", "St. Andrew's Church, Bangalore"),
    ("st. john's church", "St. John's Church, Bengaluru"),
    ("rachenahalli lake", "Rachenahalli Lake"),
    ("ub city", "UB City"),
    ("east parade church", "East Parade Church"),
    ("statue of edward vii", "Statue of Edward VII"),
    ("vr bengaluru", "VR Bengaluru"),
    ("the holy trinity church", "Holy Trinity Church, Bangalore"),
    ("koshy's", "Koshy's"),
    ("russel market", "Russell Market"),
    ("st. mary's orthodox valiapalli", "St. Mary's Orthodox Valiyapally"),
    ("shri aananda lingeshwara temple", "Sri Ananda Lingeshwara Temple"),
    ("hudson memorial church", "Hudson Memorial Church, Bengaluru"),
    ("kempambudhi kere", "Kempambudhi Lake"),
    ("rangoli gardens", "Rangoli Gardens, Jakkur"),
    ("gallery g", "Gallery G"),
    ("sri panchamukhi ganesha temple", "Mahameru Panchamukha Ganesha temple"),
    ("hosakote lake", "Hoskote Tank"),
    ("yellamallappa chetty lake", "Yellamallappchetti Lake"),
    ("mysore lancer's haifa memorial", "Mysore Lancers memorial"),
    ("sri kalikambal kamateshwarar temple", "Hosur Kalikambal Kamateshwarar Temple"),
    ("carmel school", "Carmel School, Padmanabhanagar"),
    ("the art of living international center", "The Art of Living International Center"),
    ("mahatma gandhi", "Statue of Mahatma Gandhi"),
    ("uttarahalli lake", "Uttarahalli Lake"),
    ("nayandahalli lake", "Nayandahalli lake"),
    ("mavatura kere", "Mavathoor Kere"),
    ("buddha shanti kanive", "Buddha Shanthi Kanive"),
    ("sri shanmukha temple", "Shrungagiri Sri Shanmukha Swamy Temple"),
    ("banashankari temple", "Sri Banashankari Temple, Bengaluru"),
    ("science gallery bengaluru", "Science Gallery Bengaluru"),
    ("surya narayana swamy temple", "Sri Suryanarayana Swamy Temple, Bangalore"),
    ("gopalan arcade mall", "Gopalan Arcade Mall, Rajarajeshwari Nagar"),
    ("jamsetji tata statue", "statue of Jamsetji Tata"),
    ("reverend ferdinand kittel", "Ferdinand Kittel statue"),
    ("seshadri iyer statue", "K Seshadri Iyer statue"),
]


@pytest.mark.parametrize("poi,label", WRONG)
def test_reviewed_wrong_match_is_rejected(poi, label):
    assert rejects(label, poi), f"{label!r} should NOT match {poi!r}"


@pytest.mark.parametrize("poi,label", RIGHT)
def test_reviewed_right_match_is_kept(poi, label):
    assert not rejects(label, poi), f"{label!r} should still match {poi!r}"


def test_all_85_reviewed_rows_are_covered():
    assert len(WRONG) + len(RIGHT) == 85

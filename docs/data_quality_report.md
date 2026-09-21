# NavigIQ POI data-quality report

Generated 2026-09-21T13:31:57+00:00 from the loaded database by `python -m app.ingestion.run --report-only`. Regenerate after every ingestion.

Scores are documentation/notability measures, never ratings (ADR-008).

## Totals

- Active POIs: **12,252**
- Recommendable (quality-gated discovery pool): **4,011**
- Curated by NavigIQ: **55**
- Inactive (kept for history, never served): 3
- Chain branches: 2,120
- Duplicate candidates (same name within 150 m): 2
- Missing coordinates: 0 · outside 90 km: 0
- Invalid records: {'cost_order': 0, 'duration_order': 0, 'hours_interval': 0}

## Coverage

| Field | Coverage |
|---|---|
| description | 2.0% |
| wikipedia description | 1.9% |
| opening hours reliable | 8.2% |
| opening hours any source tag | 8.6% |
| cost non default | 8.6% |
| experience tags | 100.0% |
| mood tags | 100.0% |
| source url | 100.0% |
| license | 100.0% |
| locality | 99.8% |
| district | 100.0% |
| wikidata | 1.9% |
| free image | 0.2% |

## By region

| Region | POIs | Recommendable | With description |
|---|---|---|---|
| CITY | 1,219 | 414 | 15 |
| CITY_CORE | 9,922 | 3,020 | 170 |
| NEARBY_ESCAPE | 591 | 313 | 27 |
| OUTSKIRTS | 520 | 264 | 36 |

## By distance band (km from centre)

| Band | POIs |
|---|---|
| 0-10 | 7,483 |
| 10-20 | 3,290 |
| 20-30 | 368 |
| 30-40 | 211 |
| 40-50 | 151 |
| 50-60 | 158 |
| 60-70 | 223 |
| 70-80 | 189 |
| 80-90 | 179 |

## By category

| Category | POIs |
|---|---|
| restaurant | 3,544 |
| street_food | 1,761 |
| cafe | 1,276 |
| temple | 1,226 |
| dessert | 1,055 |
| park | 637 |
| nightlife | 450 |
| lake | 337 |
| entertainment | 285 |
| church | 270 |
| mosque | 199 |
| mall | 182 |
| monument | 138 |
| shopping | 123 |
| religious_site | 118 |
| hill | 83 |
| forest | 69 |
| reservoir | 66 |
| market | 63 |
| gallery | 57 |
| other | 41 |
| heritage | 33 |
| museum | 29 |
| history | 28 |
| walking_area | 26 |
| activity | 24 |
| fort | 21 |
| garden | 19 |
| adventure | 16 |
| viewpoint | 16 |
| gaming | 15 |
| nature | 13 |
| waterfall | 8 |
| science | 8 |
| experience | 5 |
| neighborhood | 5 |
| architecture | 3 |
| palace | 3 |

## By district

| District | POIs |
|---|---|
| Bengaluru Urban | 11,030 |
| Tumakuru | 238 |
| Bengaluru North | 233 |
| Krishnagiri | 217 |
| Bengaluru South | 189 |
| Kolar | 155 |
| Chikkaballapura | 106 |
| Mandya | 65 |
| Chamarajanagar | 9 |
| Dharmapuri | 5 |
| Chittoor | 5 |

## Top localities

| Locality | POIs |
|---|---|
| Indiranagar | 848 |
| Koramangala | 554 |
| HSR Layout | 388 |
| Marathahalli | 345 |
| JP Nagar | 329 |
| Shivajinagar | 270 |
| BTM Layout | 269 |
| Yelahanka | 251 |
| Richmond Town | 251 |
| Jayanagar | 248 |
| Bellanduru | 232 |
| Malleswaram | 228 |
| EPIP Zone | 219 |
| Basavanagudi | 209 |
| Vijaya Nagar | 197 |
| Banashankari | 196 |
| Sahakaranagara | 188 |
| Whitefield | 170 |
| Halasuru | 165 |
| RMV 2nd Stage | 165 |
| Electronic City | 163 |
| Shanti Nagar | 159 |
| Rajajinagar | 156 |
| Vasanth Nagar | 152 |
| Mahalakshmi Layout | 146 |

## Opening-hours confidence

| Confidence | POIs |
|---|---|
| 0.30 | 11,244 |
| 0.60 | 9 |
| 0.90 | 999 |

## Cost confidence

| Basis | POIs |
|---|---|
| category_default | 11,194 |
| free | 1,022 |
| curated_estimate | 26 |
| source_tag | 10 |

## Pipeline manifest

```json
{
  "stages": {
    "extract": {
      "network_calls": 0,
      "cache_hits": 24,
      "osm_base": "2026-09-21T07:42:07Z",
      "food_elements": 7776,
      "nightlife_elements": 452,
      "culture_elements": 976,
      "worship_elements": 1800,
      "leisure_elements": 770,
      "nature_relief_elements": 109,
      "nature_water_elements": 479,
      "nature_land_elements": 147,
      "nature_protected_elements": 15,
      "shopping_elements": 331,
      "walking_elements": 32,
      "places_elements": 6830
    },
    "geo_filter": {
      "elements": 12887,
      "outside_envelope": 107,
      "repeat_across_groups": 78,
      "kept": 12702
    },
    "gazetteer": {
      "places": 6725,
      "districts": [
        "Annamayya",
        "Bengaluru North",
        "Bengaluru South",
        "Bengaluru Urban",
        "Chamarajanagar",
        "Chikkaballapura",
        "Chittoor",
        "Dharmapuri",
        "Kolar",
        "Krishnagiri",
        "Mandya",
        "Mysuru",
        "Sri Sathya Sai",
        "Tumakuru"
      ]
    },
    "categorize": {
      "input": 12702,
      "kept": 12334,
      "dropped_below_min_extent": 123,
      "dropped_node_without_extent": 8,
      "dropped_not_notable": 233,
      "dropped_unmapped": 4
    },
    "deduplicate": {
      "input": 12334,
      "kept": 12173,
      "merged_wikidata": 1,
      "merged_name_proximity": 160,
      "chain_branches": 2120
    },
    "wikidata_link": {
      "items": 1410,
      "linked": 73,
      "added_wikidata_only": 73
    },
    "enrich": {
      "wikidata_entities": 232,
      "wikipedia_articles": 237,
      "free_images": 172,
      "network_calls": 0,
      "cache_hits": 22
    },
    "enrich_tag": {
      "records": 12255,
      "wikipedia_description": 239,
      "free_images": 20,
      "hours_category_default": 11247,
      "hours_osm_parsed": 999,
      "hours_osm_sun": 9
    },
    "curate": {
      "entries": 55,
      "created": 12,
      "unmatched": 0,
      "unmatched_keys": [],
      "applied": 55
    },
    "absorb_curated_duplicates": {
      "absorbed": 3
    },
    "score": {
      "records": 12252,
      "recommendable": 4011
    },
    "validate": {
      "input": 12252,
      "kept": 12252
    },
    "load": {
      "unchanged": 12250,
      "updated": 2,
      "deactivated": 3
    },
    "load_places": {
      "unchanged": 6725
    }
  }
}
```

Data © OpenStreetMap contributors (ODbL); Wikipedia text CC BY-SA 4.0; Wikidata CC0.

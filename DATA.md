
## OSM extract (NQ-011)

- Source: BBBike custom extract, .osm.pbf
- Stored as: infrastructure/osrm-data/map.osm.pbf (72.7 MB, untracked)
- Checksum: data/artifacts/map.osm.pbf.sha256
- Bounding box: lat 11.9060-13.7160, lon 76.7080-78.8650
- License: ODbL - (c) OpenStreetMap contributors. Attribution is required in
  the application UI, not only in documentation.
- Extracted: 85,778 POI candidates (39,500 node / 45,841 way / 437 relation)
- Distinct tag combinations: 580 (see data/artifacts/unmapped_report.csv)
- Category mapping: 50 rules, 51 drops, 18 landmark overrides
- Note: ~57% of staging records are water features, largely unnamed rural
  ponds from the wide bbox. Dropped in NQ-013 via the category mapping.

## Opening hours coverage (NQ-014)

- POIs with an OSM opening_hours tag: 1,288 of 14,851 (8.7%)
- Successfully parsed: 1,262 (98% of those tagged, 8.5% of all POIs)
- Unparseable: 26 - malformed source values and 8 'sunrise-sunset'
- Category defaults applied: 13,589 POIs at confidence 0.3

This 8.5% figure is why low-confidence hours are a soft optimizer
constraint. It is also the single strongest argument for the curated
seed set: hand-verified hours are the difference between an itinerary
that works and one that sends someone to a closed restaurant.

## Sunset category derivation (NQ-017)

The sunset category had zero POIs: no OSM tag maps to it directly. Derived
from existing categories as secondary links in poi_category_links:

  viewpoint -> sunset @ 0.9   (150 POIs, 28 tagged tourism=viewpoint)
  lake      -> sunset @ 0.6   (481 POIs, all natural=water)
  park      -> sunset @ 0.4   (656 POIs)

1,287 sunset-capable POIs. 626 already came from the NQ-013 YAML secondary
rules; 661 were added by backfill.

search_pois currently filters on primary_category only, so these are visible
to the ranker but not to a direct category search. NQ-025 should query
poi_category_links when resolving interests.

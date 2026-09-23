"""The supported region. ONE definition, imported everywhere.

Previously the bounding box was written separately in the TripSpec schema
and the validator, and could silently drift apart. Matches the OSM extract
(ADR-009): wide enough for regional destinations like Nandi Hills (13.37).
"""
BBOX_MIN_LAT, BBOX_MAX_LAT = 11.9, 13.75
BBOX_MIN_LON, BBOX_MAX_LON = 76.7, 78.9

# City centre (Vidhana Soudha). Used to prefer the Bengaluru 'Koramangala'
# over a village of the same name 45 km away.
CENTRE_LAT, CENTRE_LON = 12.9794, 77.5912


def in_region(lat: float, lon: float) -> bool:
    return (BBOX_MIN_LAT <= lat <= BBOX_MAX_LAT
            and BBOX_MIN_LON <= lon <= BBOX_MAX_LON)
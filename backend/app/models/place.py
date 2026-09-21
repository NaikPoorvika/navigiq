"""NQ-011b - Place gazetteer.

Resolves a place NAME to coordinates. The LLM must never produce coordinates
(ADR-002), so "from Indiranagar" needs a lookup that returns a real point or
admits it does not know.

Separate from pois: 'Indiranagar' as a suburb is a different thing from
'Indiranagar Library'. Searching pois for a neighbourhood returns a library,
a plaque and a bar.
"""
from __future__ import annotations

from sqlalchemy import Column, Index, Integer, String, UniqueConstraint
from geoalchemy2 import Geography

from app.db.base_class import Base


class Place(Base):
    __tablename__ = "places"

    id = Column(Integer, primary_key=True)
    source_ref = Column(String(60), nullable=False)
    name = Column(String(200), nullable=False)
    # unaccent + lower, for trigram matching. Users type "Malleshwaram";
    # OSM says "Malleswaram".
    name_normalized = Column(String(200), nullable=False)
    kind = Column(String(20), nullable=False)
    geom = Column(Geography("POINT", srid=4326), nullable=False)
    population = Column(Integer)
    wikidata_id = Column(String(20))

    __table_args__ = (
        UniqueConstraint("source_ref", name="uq_places_source_ref"),
        Index("ix_places_name_trgm", "name_normalized",
              postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}),
        Index("ix_places_kind", "kind"),
    )
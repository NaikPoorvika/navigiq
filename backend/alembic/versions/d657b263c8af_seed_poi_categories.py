"""seed poi_categories

Revision ID: d657b263c8af
Revises: a95eba6f3f2c
Create Date: 2026-09-21 14:46:36.993224

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd657b263c8af'
down_revision: Union[str, Sequence[str], None] = 'a95eba6f3f2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # The 20 closed categories. Must match the Category enum in
    # app/schemas/tripspec.py exactly - test_category_parity enforces it.
    # default_visit_minutes is authoritative; never hardcode durations.
    # ON CONFLICT makes this safe on databases seeded by hand earlier.
    op.execute("""
        INSERT INTO poi_categories
            (id, key, display_name, default_visit_minutes, is_indoor,
             weather_sensitive, typical_cost_inr, meal_category)
        VALUES
            (1,'cafe','Cafe',45,true,false,300,true),
            (2,'restaurant','Restaurant',75,true,false,600,true),
            (3,'street_food','Street Food',30,false,true,150,true),
            (4,'bar','Bar',90,true,false,800,false),
            (5,'dessert','Dessert',30,true,false,200,false),
            (6,'historical','Historical Site',60,false,true,50,false),
            (7,'temple','Temple',30,false,true,0,false),
            (8,'museum','Museum',90,true,false,100,false),
            (9,'art_gallery','Art Gallery',60,true,false,50,false),
            (10,'park','Park',60,false,true,0,false),
            (11,'lake','Lake',45,false,true,0,false),
            (12,'viewpoint','Viewpoint',30,false,true,0,false),
            (13,'sunset','Sunset Spot',45,false,true,0,false),
            (14,'nature','Nature',90,false,true,0,false),
            (15,'shopping','Shopping',60,true,false,0,false),
            (16,'market','Market',45,false,true,0,false),
            (17,'bookstore','Bookstore',45,true,false,0,false),
            (18,'nightlife','Nightlife',120,true,false,1000,false),
            (19,'entertainment','Entertainment',120,true,false,400,false),
            (20,'landmark','Landmark',30,false,true,0,false)
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute(
        "SELECT setval(pg_get_serial_sequence('poi_categories','id'), 20, true)")


def downgrade() -> None:
    # Intentionally a no-op. Every POI references a category, so deleting
    # these rows would either fail on the foreign key or orphan 14,851 POIs.
    pass
# Import all the models here so that Alembic can read them
from app.db.base_class import Base
from app.models.user import User

# This allows Alembic to easily import `Base` from `app.db.base`

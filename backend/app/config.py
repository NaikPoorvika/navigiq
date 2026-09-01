from pydantic_settings import BaseSettings
from typing import List, Union

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str
    
    # CORS
    CORS_ORIGINS: Union[str, List[str]] = []
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

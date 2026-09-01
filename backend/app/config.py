from pydantic_settings import BaseSettings
from typing import List, Union

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str
    
    # CORS
    CORS_ORIGINS: Union[str, List[str]] = []
    
    # Security
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

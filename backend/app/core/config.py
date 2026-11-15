from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "GrowthCognix API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://growth:growth@db:5432/growthcognix"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me-in-.env"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 8
    cors_origins: str = "http://localhost:3000"
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 20

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

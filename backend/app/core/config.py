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

    # ---- Phase 2: AI providers (free tiers; keys live only in server env) ----
    # Which provider handles long business/document analysis and which handles fast short calls.
    ai_analysis_provider: str = "gemini"  # gemini | groq | none
    ai_fast_provider: str = "groq"  # gemini | groq | none
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ai_timeout_seconds: int = 90
    # Run analysis jobs in-process instead of on the Redis worker (dev/tests only).
    analysis_inline: bool = False
    # Website analysis limits
    website_max_pages: int = 5
    website_max_bytes: int = 2_000_000
    website_allow_private: bool = False  # SSRF guard; never enable in production

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

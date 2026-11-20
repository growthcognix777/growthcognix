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

    # ---- Phase 3: crawler, audit, competitors ----
    crawler_provider: str = "native"  # native (built-in, robots-aware) | firecrawl
    firecrawl_api_url: str = ""  # self-hosted (e.g. http://firecrawl:3002) or https://api.firecrawl.dev
    firecrawl_api_key: str = ""
    crawl_max_pages_limit: int = 500  # hard ceiling regardless of per-crawl config
    crawl_default_max_pages: int = 50
    crawl_default_max_depth: int = 3
    crawl_default_delay_seconds: float = 1.0
    crawl_timeout_seconds: int = 20
    crawl_max_bytes: int = 3_000_000
    competitor_max_pages: int = 25
    pagespeed_api_key: str = ""  # Google PageSpeed Insights API (free key); empty = PageSpeed skipped

    # ---- Phase 4: buyer discovery providers (all optional; none configured = manual/directory only) ----
    searxng_url: str = ""  # self-hosted SearXNG with the JSON format enabled, e.g. http://searxng:8080 (free)
    brave_api_key: str = ""  # Brave Search API: no free plan since Feb 2026, $5/month credit (~1,000 queries), card required
    google_pse_key: str = ""  # Google Programmable Search JSON API: ~100 free queries/day
    google_pse_cx: str = ""
    comtrade_api_key: str = ""  # optional; the UN Comtrade public preview API needs no key (500 rows/call)
    discovery_daily_limit_searxng: int = 500
    discovery_daily_limit_brave: int = 30  # keeps a month inside the $5 credit
    discovery_daily_limit_google_pse: int = 100
    discovery_daily_limit_directory: int = 50
    discovery_results_per_query: int = 10
    discovery_max_companies: int = 200  # per campaign ceiling
    discovery_verify_pages: int = 3  # pages fetched per prospect site (home + contact/about)
    discovery_provider_timeout: int = 20

    # ---- Phase 5: marketing. Publishing uses official APIs only; every value optional. ----
    marketing_token_key: str = ""  # Fernet key (urlsafe base64, 32 bytes) for OAuth tokens; required to connect accounts
    public_api_url: str = "http://localhost:8000"  # where OAuth providers redirect back to (…/api/v1/marketing/oauth/{platform}/callback)
    public_app_url: str = "http://localhost:3000"  # where the browser returns after OAuth
    meta_app_id: str = ""  # Meta app (Facebook Pages + Instagram Graph API); publishing needs App Review for pages_manage_posts etc.
    meta_app_secret: str = ""
    meta_graph_version: str = "v27.0"  # verified 2026-11-17 (v21.0 removed 2027-01-21)
    linkedin_client_id: str = ""  # LinkedIn app; organisation posting needs the Community Management API product
    linkedin_client_secret: str = ""
    linkedin_api_version: str = "202610"  # monthly YYYYMM, ~1 year support; verified 2026-11-17
    marketing_http_timeout: int = 20

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

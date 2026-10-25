"""Settings, read once from the environment (and a local .env) at startup."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- database ---------------------------------------------------------
    # Supabase session pooler, with SQLAlchemy's async driver.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/maroonway"
    db_echo: bool = False

    @field_validator("database_url")
    @classmethod
    def _async_postgres_url(cls, value: str) -> str:
        """Accept the URLs people actually paste, and reject the wrong ones clearly.

        Supabase offers several strings and only one of them is a database
        connection. Pasting the project URL instead used to reach SQLAlchemy as
        a dialect name and die with ``Can't load plugin:
        sqlalchemy.dialects:https`` -- eighty lines of traceback that never
        mention the variable at fault.

        A psql-style URL is rewritten rather than refused: ``postgresql://`` is
        what every tool but this one prints, and demanding the ``+asyncpg``
        suffix by hand is a trap with no upside.
        """
        url = value.strip()
        if not url:
            raise ValueError("DATABASE_URL is empty; set it to the Postgres connection string")

        scheme = url.split("://", 1)[0].lower() if "://" in url else ""
        if scheme in {"postgres", "postgresql"}:
            return "postgresql+asyncpg://" + url.split("://", 1)[1]
        if scheme.startswith("postgresql+"):
            return url
        if scheme in {"http", "https"}:
            raise ValueError(
                "DATABASE_URL looks like a project URL, not a database connection "
                f"({url.split('://', 1)[0]}://...). In Supabase this is Project "
                "Settings > Database > Connection string > Session pooler, which "
                "starts postgresql:// and contains a host, port 5432 and a password."
            )
        raise ValueError(
            f"DATABASE_URL must be a Postgres connection string, got scheme "
            f"{scheme or '(none)'!r}. Expected postgresql:// or postgresql+asyncpg://."
        )

    # --- upstream data ----------------------------------------------------
    rmp_school_id: str = "1003"  # A&M College Station; Galveston is 1006
    rmp_refetch_days: int = 7

    # --- Gemini -----------------------------------------------------------
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-lite-latest"
    summary_rpm: int = 10
    summary_max_comments: int = 60
    summary_comment_chars: int = 600

    # --- Jev (TypeSafe AI decision model) ---
    typesafe_api_key: str | None = None
    jev_model: str = "jev-latest"
    jev_base_url: str | None = None
    #: Reviews fed to one trait decision. Jev's context is 32k tokens and bills
    #: input only, so this can be generous.
    trait_max_reviews: int = 40

    # --- hot cache --------------------------------------------------------
    # The professor cache is the "recently viewed" cache: LRU eviction means the
    # professors people just opened are exactly the ones that stay resident.
    cache_professor_size: int = 512
    cache_professor_ttl: float = 15 * 60
    cache_search_size: int = 256
    cache_search_ttl: float = 5 * 60
    # Short TTL for "no such professor", so a hammered bad id can't re-query Postgres.
    cache_negative_ttl: float = 30.0
    # Professors pre-loaded at boot so the first click of a demo is a HIT.
    cache_warm_count: int = 25
    recents_size: int = 50

    # --- scoring ----------------------------------------------------------
    # Ratings needed before a professor's own average outweighs the global mean.
    scoring_prior_weight: float = 10.0
    weight_rating: float = 1.0
    weight_would_take_again: float = 0.3
    weight_gpa: float = 0.4
    weight_difficulty: float = -0.5

    # --- misc -------------------------------------------------------------
    admin_token: str | None = None
    #: Shared secret the Next.js server sends with a signed-in student's
    #: identity. The backend trusts the header only when this matches, because
    #: the frontend is the only thing that has verified a Google session.
    internal_token: str | None = None
    #: Guards POST /sections/import. Falls back to admin_token when unset.
    import_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

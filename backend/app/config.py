"""Application settings loaded from environment variables (and .env)."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "change-me-to-a-long-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # General
    app_env: str = "development"
    allowed_origin: str = "http://localhost:5173"  # comma-separated list
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # Database. `mock://` uses an in-memory mongomock DB (dev/tests only).
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "launchcrew"

    # LLM (Groq). Model names intentionally have NO defaults: set them in .env.
    mock_llm: bool = True
    groq_api_key: str = ""
    # Optional comma-separated pool. Several keys let the client rotate between
    # them and cool down only the key that returned 429, so one rate limit does
    # not stall a run. Merged with groq_api_key; duplicates ignored.
    groq_api_keys: str = ""
    groq_model: str = ""
    groq_fast_model: str = ""
    groq_vision_model: str = ""
    llm_max_concurrency: int = 2
    llm_max_retries: int = 5
    # How long a key stays parked after a 429 that carries no retry-after header.
    llm_key_cooldown_s: float = 60.0
    llm_request_timeout_s: float = 90.0
    llm_backoff_base_s: float = 1.0
    llm_backoff_max_s: float = 30.0

    # Tools
    tavily_api_key: str = ""
    netlify_auth_token: str = ""

    # Guardrails
    max_steps: int = 30
    max_token_budget: int = 150_000
    agent_timeout_s: float = 240.0
    max_critic_iterations: int = 3
    tool_rounds_cap: int = 3
    runs_per_hour: int = 10
    max_revisions: int = 5
    engineer_max_tokens: int = 6000

    # Artifact storage (HTML + screenshots): "mongo" (default, survives redeploys) or "local" (STORAGE_DIR).
    storage_backend: str = "mongo"
    storage_dir: str = "./data/artifacts"

    @field_validator("mongo_uri", "mongo_db", "allowed_origin", "storage_backend", "storage_dir", mode="before")
    @classmethod
    def _blank_is_unset(cls, value, info):
        """A key left empty in .env means "not set", not "the empty string": an empty MONGO_URI
        reaches motor as a host list of one blank entry and wedges startup before the first request."""
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[info.field_name].default
        return value

    @property
    def origins(self) -> list[str]:
        return self.allowed_origins

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origin.split(",") if o.strip()]

    @property
    def groq_key_pool(self) -> list[str]:
        """Keys to rotate between: GROQ_API_KEY plus any comma-separated GROQ_API_KEYS,
        deduplicated in the order they were written."""
        seen: set[str] = set()
        pool: list[str] = []
        for chunk in f"{self.groq_api_key},{self.groq_api_keys}".split(","):
            key = chunk.strip()
            if key and key not in seen:
                seen.add(key)
                pool.append(key)
        return pool

    def validate_for_runtime(self) -> None:
        """Fail fast on configuration that would otherwise break mid-run."""
        if self.app_env == "production" and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise RuntimeError("JWT_SECRET must be changed in production.")
        if not self.mock_llm:
            missing = [n for n, v in (("GROQ_API_KEY", self.groq_key_pool), ("GROQ_MODEL", self.groq_model)) if not v]
            if missing:
                raise RuntimeError(
                    f"MOCK_LLM=false but {', '.join(missing)} not set. Set them in .env "
                    "(check model names in Groq's docs) or use MOCK_LLM=true."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
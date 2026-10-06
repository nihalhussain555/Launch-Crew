"""Application settings loaded from environment variables (and .env)."""
from functools import lru_cache

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
    groq_model: str = ""
    groq_fast_model: str = ""
    groq_vision_model: str = ""
    llm_max_concurrency: int = 2
    llm_max_retries: int = 5
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
    engineer_max_tokens: int = 6000

    # Artifact storage (HTML + screenshots): "mongo" (default, survives redeploys) or "local" (STORAGE_DIR).
    storage_backend: str = "mongo"
    storage_dir: str = "./data/artifacts"

    @property
    def origins(self) -> list[str]:
        return self.allowed_origins

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origin.split(",") if o.strip()]

    def validate_for_runtime(self) -> None:
        """Fail fast on configuration that would otherwise break mid-run."""
        if self.app_env == "production" and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise RuntimeError("JWT_SECRET must be changed in production.")
        if not self.mock_llm:
            missing = [n for n, v in (("GROQ_API_KEY", self.groq_api_key), ("GROQ_MODEL", self.groq_model)) if not v]
            if missing:
                raise RuntimeError(
                    f"MOCK_LLM=false but {', '.join(missing)} not set. Set them in .env "
                    "(check model names in Groq's docs) or use MOCK_LLM=true."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
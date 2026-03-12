from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# プロジェクトルートの .env を探索（backend/ からでも動作するように）
_ENV_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if not _ENV_FILE.exists():
    _ENV_FILE = Path(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), case_sensitive=True)

    # === LLM API ===
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # === Database ===
    POSTGRES_HOST: str = "proposal-creation-postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "proposal_creation"
    POSTGRES_USER: str = "proposal_user"
    POSTGRES_PASSWORD: str = ""

    NEO4J_URI: str = "bolt://proposal-creation-neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # === Observability ===
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "proposal-creation-phase1"

    # === Embedding ===
    EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_BATCH_SIZE: int = 50

    # === Search ===
    SEARCH_VECTOR_WEIGHT: float = 0.7
    SEARCH_KEYWORD_WEIGHT: float = 0.3
    SEARCH_TOP_K: int = 10

    # === App Config ===
    LLM_LIGHT_MODEL: str = "gpt-4o-mini"
    LLM_HEAVY_MODEL: str = "claude-sonnet-4-5-20250929"
    MAPPING_MAX_CONCURRENCY: int = 5
    MAPPING_ERROR_THRESHOLD: float = 0.2

    # === CORS ===
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    @property
    def langsmith_enabled(self) -> bool:
        """LangSmith トレーシングが有効かどうか。"""
        return self.LANGCHAIN_TRACING_V2 and bool(self.LANGCHAIN_API_KEY)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        """Alembic用の同期URL"""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


def get_settings() -> Settings:
    return Settings()

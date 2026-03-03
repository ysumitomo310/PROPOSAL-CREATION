import os

from app.core.config import Settings


def test_settings_defaults():
    settings = Settings(
        POSTGRES_PASSWORD="test",
        NEO4J_PASSWORD="test",
    )
    assert settings.POSTGRES_HOST == "proposal-creation-postgres"
    assert settings.POSTGRES_PORT == 5432
    assert settings.POSTGRES_DB == "proposal_creation"
    assert settings.MAPPING_MAX_CONCURRENCY == 5
    assert settings.MAPPING_ERROR_THRESHOLD == 0.2
    assert settings.LLM_LIGHT_MODEL == "gpt-4o-mini"


def test_settings_database_url():
    settings = Settings(
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5435,
        POSTGRES_DB="test_db",
        POSTGRES_USER="test_user",
        POSTGRES_PASSWORD="test_pass",
        NEO4J_PASSWORD="test",
    )
    assert settings.database_url == "postgresql+asyncpg://test_user:test_pass@localhost:5435/test_db"
    assert settings.database_url_sync == "postgresql://test_user:test_pass@localhost:5435/test_db"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "env_pass")
    monkeypatch.setenv("NEO4J_PASSWORD", "env_neo4j")
    monkeypatch.setenv("MAPPING_MAX_CONCURRENCY", "10")
    settings = Settings(_env_file=None)
    assert settings.POSTGRES_PASSWORD == "env_pass"
    assert settings.MAPPING_MAX_CONCURRENCY == 10

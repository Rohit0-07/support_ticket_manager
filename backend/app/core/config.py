from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or defaults."""

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./tickets.db"

    # CSV data directory (relative to project root)
    CSV_DIR: Path = Path(__file__).resolve().parents[3] / "sample_data"

    # Pagination defaults
    DEFAULT_PAGE_LIMIT: int = 50
    MAX_PAGE_LIMIT: int = 500

    # Auto-seed on startup
    AUTO_SEED_ON_STARTUP: bool = False

    model_config = SettingsConfigDict(env_prefix="STM_")


settings = Settings()

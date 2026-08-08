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

    # Similarity Engine settings (env prefix: STM_)
    SIMILARITY_TOP_N_DEFAULT: int = 3
    SIMILARITY_TOP_N_MAX: int = 10
    SIMILARITY_MIN_SCORE: float = 0.10          # below this → NO_SIMILAR_CASES
    SIMILARITY_MIN_MEANINGFUL_TOKENS: int = 3   # EC-03 damping threshold
    SIMILARITY_MAX_QUERY_CHARS: int = 512       # EC-06 truncation length
    SIMILARITY_DEDUPE_IDENTICAL: bool = True    # EC-04

    # Resolution Engine settings (env prefix: STM_)
    RESOLUTION_CONFIDENCE_THRESHOLD: float = 0.75   # BR-02 default confidence bar
    RESOLUTION_TOP_N_PRECEDENTS: int = 3            # BR-01 top-N precedent set
    RESOLUTION_PARTIAL_REFUND_RATIO: float = 0.5    # partial_refund = 50% of order value (BR-05)

    model_config = SettingsConfigDict(env_prefix="STM_")


settings = Settings()

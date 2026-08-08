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

    # Reply Drafting settings (env prefix: STM_)
    REPLY_MIN_QUOTE_CHARS: int = 3      # EC-03: below this → ACKNOWLEDGMENT variant (no description quote)
    REPLY_MAX_QUOTE_CHARS: int = 120    # EC-06: truncate long description quotes with "…"
    REPLY_MAX_EVIDENCE_CITES: int = 3   # cite at most this many evidence ids (aligned to F3 top-N)

    # Dashboard settings (env prefix: STM_)
    DASHBOARD_PREVIEW_CHARS: int = 120      # EC-03: card description truncation length (aligns with F4 quote ceiling)
    DASHBOARD_CONFIDENCE_HIGH: float = 0.75  # EC-04: high-confidence bucket floor (aligns with F3 threshold)
    DASHBOARD_CONFIDENCE_MEDIUM: float = 0.40  # EC-04: medium-confidence bucket floor
    DASHBOARD_TOP_EVIDENCE: int = 3         # BR-03: top-N evidence shown (aligns with F3 top-N precedents)

    model_config = SettingsConfigDict(env_prefix="STM_")


settings = Settings()

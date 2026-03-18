from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List, Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./coach.db"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"

    # QVeris — primary + up to 4 backup keys
    QVERIS_API_KEY: str = ""
    QVERIS_API_KEY_2: str = ""
    QVERIS_API_KEY_3: str = ""
    QVERIS_API_KEY_4: str = ""
    QVERIS_API_KEY_5: str = ""
    QVERIS_BASE_URL: str = "https://qveris.ai/api/v1"

    # Auth
    # 固定账号密码（MVP 阶段）
    APP_USERNAME: str = "123456"
    APP_PASSWORD: str = "abc123"
    # JWT 签名密钥（生产请在 .env 中覆盖）
    SECRET_KEY: str = "trademind-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # Set to true to wipe market_data/trades and re-seed with real K-line data
    FORCE_RESEED: bool = False

    # Supabase (optional — if set, overrides DATABASE_URL)
    SUPABASE_DATABASE_URL: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def effective_database_url(self) -> str:
        """Return Supabase URL when configured, otherwise fall back to DATABASE_URL."""
        return self.SUPABASE_DATABASE_URL or self.DATABASE_URL

    def all_qveris_keys(self) -> List[str]:
        """Return all non-empty QVeris API keys in priority order."""
        candidates = [
            self.QVERIS_API_KEY,
            self.QVERIS_API_KEY_2,
            self.QVERIS_API_KEY_3,
            self.QVERIS_API_KEY_4,
            self.QVERIS_API_KEY_5,
        ]
        return [k for k in candidates if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = "sqlite:///./data/catalog.db"
    upload_dir: Path = Path("./data/uploads")
    frontend_dist_dir: Path | None = Field(default=None, validation_alias="FRONTEND_DIST_DIR")
    ai_provider: str = Field(default="auto", validation_alias="AI_PROVIDER")
    avalai_api_key: str | None = Field(default=None, validation_alias="AVALAI_API_KEY")
    avalai_base_url: str = Field(
        default="https://api.avalai.ir/v1", validation_alias="AVALAI_BASE_URL"
    )
    avalai_vision_model: str = Field(default="gpt-5.4", validation_alias="AVALAI_VISION_MODEL")
    avalai_text_model: str = Field(default="gpt-5.4", validation_alias="AVALAI_TEXT_MODEL")
    avalai_stt_model: str = Field(
        default="gpt-4o-mini-transcribe", validation_alias="AVALAI_STT_MODEL"
    )
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()

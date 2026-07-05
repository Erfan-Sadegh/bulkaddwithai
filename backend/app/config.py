from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    frontend_url: str = Field(default="http://127.0.0.1:5173", validation_alias="FRONTEND_URL")
    basalam_client_id: str | None = Field(default=None, validation_alias="BASALAM_CLIENT_ID")
    basalam_client_secret: str | None = Field(default=None, validation_alias="BASALAM_CLIENT_SECRET")
    basalam_redirect_uri: str | None = Field(default=None, validation_alias="BASALAM_REDIRECT_URI")
    basalam_scopes: str = Field(
        default="vendor.profile.read vendor.product.read vendor.product.write customer.profile.read",
        validation_alias="BASALAM_SCOPES",
    )
    basalam_auth_url: str = Field(
        default="https://basalam.com/accounts/sso", validation_alias="BASALAM_AUTH_URL"
    )
    basalam_token_url: str = Field(
        default="https://auth.basalam.com/oauth/token", validation_alias="BASALAM_TOKEN_URL"
    )
    basalam_api_base_url: str = Field(
        default="https://openapi.basalam.com", validation_alias="BASALAM_API_BASE_URL"
    )
    basalam_legacy_core_base_url: str = Field(
        default="https://core.basalam.com", validation_alias="BASALAM_LEGACY_CORE_BASE_URL"
    )
    basalam_default_category_id: int | None = Field(
        default=None, validation_alias="BASALAM_DEFAULT_CATEGORY_ID"
    )
    basalam_default_stock: int = Field(default=1, validation_alias="BASALAM_DEFAULT_STOCK")
    basalam_default_status: int | None = Field(default=None, validation_alias="BASALAM_DEFAULT_STATUS")
    basalam_default_preparation_days: int = Field(
        default=1, validation_alias="BASALAM_DEFAULT_PREPARATION_DAYS"
    )
    basalam_default_weight_grams: int = Field(
        default=300, validation_alias="BASALAM_DEFAULT_WEIGHT_GRAMS"
    )
    basalam_default_package_weight_grams: int = Field(
        default=500, validation_alias="BASALAM_DEFAULT_PACKAGE_WEIGHT_GRAMS"
    )
    basalam_default_unit_quantity: int = Field(
        default=1, validation_alias="BASALAM_DEFAULT_UNIT_QUANTITY"
    )
    basalam_default_unit_type_id: int = Field(
        default=6304, validation_alias="BASALAM_DEFAULT_UNIT_TYPE_ID"
    )
    basalam_category_cache_ttl_seconds: int = Field(
        default=86400, validation_alias="BASALAM_CATEGORY_CACHE_TTL_SECONDS"
    )
    basalam_category_suggestion_threshold: float = Field(
        default=0.62, validation_alias="BASALAM_CATEGORY_SUGGESTION_THRESHOLD"
    )
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("basalam_default_category_id", "basalam_default_status", mode="before")
    @classmethod
    def empty_optional_int(cls, value):
        if value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

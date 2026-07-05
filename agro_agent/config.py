from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MCP_SCRIPT = PROJECT_ROOT / "app_mcp.py"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    agro_model: str = Field(default="gemini-2.5-flash", validation_alias="AGRO_MODEL")
    mcp_script_path: Path = Field(default=DEFAULT_MCP_SCRIPT)
    custom_farms_db_path: Path = Field(default=PROJECT_ROOT / "data" / "custom_farms.db")
    nominatim_user_agent: str = Field(
        default="agro-climate-intelligence-agent/0.2.0",
        validation_alias="NOMINATIM_USER_AGENT",
    )

    @property
    def mcp_script_resolved(self) -> Path:
        return self.mcp_script_path.resolve()

    def has_api_key(self) -> bool:
        return bool(self.google_api_key and self.google_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

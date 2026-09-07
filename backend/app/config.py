"""Application configuration loaded from environment variables."""

from pathlib import Path
from typing import Any
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ──────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./scada.db"

    # ── JWT / Auth ────────────────────────────────────────────────────
    jwt_secret_key: str = "CHANGE-ME-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 60
    jwt_refresh_expire_minutes: int = 10080  # 7 days

    # ── Modbus Gateway ────────────────────────────────────────────────
    modbus_poll_interval_ms: int = 1000
    register_map_path: str = str(
        Path(__file__).resolve().parent.parent / "register_map.yaml"
    )
    mock_modbus_enabled: bool = False
    mock_modbus_host: str = "127.0.0.1"
    mock_modbus_port: int = 5020

    # ── Command Cooldowns ─────────────────────────────────────────────
    command_min_run_seconds: int = 30
    command_min_rest_seconds: int = 60

    # ── Rules Engine ──────────────────────────────────────────────────
    schedule_retry_attempts: int = 5
    schedule_retry_base_seconds: float = 5.0
    threshold_dwell_default_seconds: int = 120
    override_default_expiry_hours: int = 4

    # ── Server ────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:8000"]
    
    def model_post_init(self, __context: Any) -> None:
        if not self.debug and self.jwt_secret_key == "CHANGE-ME-in-production":
            raise ValueError("Insecure JWT secret in production mode. Set JWT_SECRET_KEY.")


settings = Settings()

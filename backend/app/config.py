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

    # Initial customer credentials; no generators or simulation data are seeded.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

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
        insecure_secrets = {
            "CHANGE-ME-in-production",
            "change_this_jwt_secret_in_production",
            "generate_a_random_32_byte_hex_secret",
        }
        if not self.debug and (
            self.jwt_secret_key in insecure_secrets or len(self.jwt_secret_key) < 32
        ):
            raise ValueError(
                "Insecure JWT secret in production mode. Set JWT_SECRET_KEY to at least 32 random characters."
            )

        bootstrap_values = (self.bootstrap_admin_email, self.bootstrap_admin_password)
        if any(bootstrap_values) and not all(bootstrap_values):
            raise ValueError(
                "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be set together."
            )
        if self.bootstrap_admin_password and len(self.bootstrap_admin_password) < 12:
            raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters.")


settings = Settings()

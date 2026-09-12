from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    local_auth_disabled: bool = False

    supabase_url: str
    supabase_jwt_secret: str = ""
    supabase_jwt_issuer: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_service_role_key: str
    database_url: str

    worker_secret: str = Field(min_length=32)
    api_key_pepper: str = Field(min_length=32)
    dataset_bucket: str = "dataset-files"
    defect_reference_bucket: str = "defect-references"
    # Customer-supplied 3D models and environment maps. Private, like every other bucket.
    customer_asset_bucket: str = "customer-assets"
    signed_url_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    max_image_count: int = Field(default=10000, ge=1, le=100000)
    api_key_requests_per_minute: int = Field(default=120, ge=1, le=10000)
    worker_stale_seconds: int = Field(default=180, ge=30)
    job_heartbeat_seconds: int = Field(default=20, ge=5)
    worker_output_root: str = "./var/worker-output"
    # v2 is the production renderer. Legacy remains readable for old jobs, but a new
    # deployment must never silently advertise or run the blade-only compatibility path.
    render_engine_version: Literal["legacy", "v2"] = "v2"

    resend_api_key: str | None = None
    invitation_from_email: str | None = None
    frontend_url: str = "http://localhost:3000"
    runpod_api_key: str | None = None
    runpod_endpoint_id: str | None = None
    runpod_callback_secret: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.invitation_from_email)

    @property
    def runpod_enabled(self) -> bool:
        return bool(self.runpod_api_key and self.runpod_endpoint_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()

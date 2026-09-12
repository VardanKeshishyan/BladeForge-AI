from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../backend/.env.local", ".env", ".env.local", Path(__file__).resolve().parents[1] / ".env.gemini.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    api_url: str = "http://localhost:8000"
    worker_secret: str = Field(min_length=32)
    worker_name: str = "local-blender-worker"
    worker_organization_id: str | None = None
    blender_executable: str = "blender"
    render_engine_path: Path = Path("../render_engine/main.py")
    render_engine_version: Literal["legacy", "v2"] = "v2"
    render_engine_v2_path: Path = Path("../render_engine/v2/main.py")
    output_root: Path = Path("../backend/var/worker-output")
    poll_seconds: float = Field(default=3, ge=0.5, le=60)
    request_timeout_seconds: float = Field(default=30, ge=5)
    base_seed: int = 8675309
    gemini_api_key: SecretStr = SecretStr("")
    gemini_image_model: str = "gemini-3.1-flash-image"
    gemini_timeout_seconds: float = Field(default=180, ge=10, le=600)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key.get_secret_value().strip())

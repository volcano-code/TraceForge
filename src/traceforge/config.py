from pathlib import Path
from typing import Literal
import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TF_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///.traceforge/control.db"
    data_dir: Path = Path(".traceforge")
    execution_backend: Literal["reviewed_subprocess", "docker_fixture"] = "reviewed_subprocess"
    sandbox_image_id: str = ""
    sandbox_docker_host: str = "unix:///run/user/" + str(getattr(os, "getuid", lambda: 1000)()) + "/docker.sock"
    developer_token: str = ""
    reviewer_token: str = ""
    webhook_secret: str = ""
    approval_ttl_seconds: int = Field(default=900, ge=1, le=86400)
    lease_seconds: int = Field(default=60, ge=5, le=3600)
    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)

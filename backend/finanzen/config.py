"""Runtime configuration, read from environment variables only."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    version: str
    port: int
    database_url: str
    data_dir: Path
    web_dir: Path


def load_settings() -> Settings:
    return Settings(
        version=os.environ.get("APP_VERSION", "dev"),
        port=int(os.environ.get("PORT", "43651")),
        database_url=os.environ.get("DATABASE_URL", ""),
        data_dir=Path(os.environ.get("DATA_DIR", "/data")),
        web_dir=Path(os.environ.get("WEB_DIR", Path(__file__).resolve().parents[2] / "web")),
    )

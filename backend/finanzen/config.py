"""Runtime configuration, read from environment variables only."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_WEB_DIR = Path(__file__).resolve().parents[2] / "web" / "build"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    version: str = "dev"
    port: int = 43651
    public_url: str = "http://localhost:43651"
    database_url: str = ""
    data_dir: Path = Path("/data")
    web_dir: Path = DEFAULT_WEB_DIR
    session_key: str = ""
    trusted_proxy: bool = False
    dev_login: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email groups"
    oidc_admin_group: str = "admins"
    oidc_provider_name: str = "Kanonenwiese SSO"
    avatar_hosts: tuple[str, ...] = field(default_factory=tuple)
    log_level: str = "info"
    price_sync_schedule: str = "30 23 * * 1-5"
    price_stale_days: int = 3
    scheduler: bool = True

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def public_origin(self) -> str:
        parsed = urlparse(self.public_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url.rstrip('/')}/auth/callback"


def load_settings() -> Settings:
    env = os.environ
    hosts = tuple(h.strip().lower() for h in env.get("AVATAR_HOSTS", "").split(",") if h.strip())
    return Settings(
        version=env.get("APP_VERSION", "dev"),
        port=int(env.get("PORT", "43651")),
        public_url=env.get("PUBLIC_URL", "http://localhost:43651").rstrip("/"),
        database_url=env.get("DATABASE_URL", ""),
        data_dir=Path(env.get("DATA_DIR", "/data")),
        web_dir=Path(env.get("WEB_DIR", str(DEFAULT_WEB_DIR))),
        session_key=env.get("SESSION_KEY", ""),
        trusted_proxy=_bool(env.get("TRUSTED_PROXY")),
        dev_login=_bool(env.get("DEV_LOGIN")),
        oidc_issuer=env.get("OIDC_ISSUER", "").rstrip("/"),
        oidc_client_id=env.get("OIDC_CLIENT_ID", ""),
        oidc_client_secret=env.get("OIDC_CLIENT_SECRET", ""),
        oidc_scopes=env.get("OIDC_SCOPES", "openid profile email groups"),
        oidc_admin_group=env.get("OIDC_ADMIN_GROUP", "admins"),
        oidc_provider_name=env.get("OIDC_PROVIDER_NAME", "Kanonenwiese SSO"),
        avatar_hosts=hosts,
        log_level=env.get("LOG_LEVEL", "info"),
        price_sync_schedule=env.get("PRICE_SYNC_SCHEDULE", "30 23 * * 1-5"),
        price_stale_days=int(env.get("PRICE_STALE_DAYS", "3")),
        scheduler=_bool(env.get("SCHEDULER"), True),
    )

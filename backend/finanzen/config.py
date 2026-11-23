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
    backup_schedule: str = "30 3 * * *"
    backup_keep_days: int = 30
    secrets_key: str = ""
    fints_product_id: str = ""
    fints_sync_schedule: str = "15 5 * * *"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"  # starttls | ssl | none
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    notify_schedule: str = "0 8 * * *"
    report_schedule: str = "0 8 1 * *"

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

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
        backup_schedule=env.get("BACKUP_SCHEDULE", "30 3 * * *"),
        backup_keep_days=int(env.get("BACKUP_KEEP_DAYS", "30")),
        secrets_key=env.get("SECRETS_KEY", ""),
        fints_product_id=env.get("FINTS_PRODUCT_ID", ""),
        fints_sync_schedule=env.get("FINTS_SYNC_SCHEDULE", "15 5 * * *"),
        smtp_host=env.get("SMTP_HOST", ""),
        smtp_port=int(env.get("SMTP_PORT", "587") or "587"),
        smtp_security=env.get("SMTP_SECURITY", "starttls").strip().lower() or "starttls",
        smtp_user=env.get("SMTP_USER", ""),
        smtp_password=env.get("SMTP_PASSWORD", ""),
        smtp_from=env.get("SMTP_FROM", ""),
        vapid_public_key=env.get("VAPID_PUBLIC_KEY", "").strip(),
        vapid_private_key=env.get("VAPID_PRIVATE_KEY", "").strip(),
        vapid_subject=env.get("VAPID_SUBJECT", "").strip(),
        notify_schedule=env.get("NOTIFY_SCHEDULE", "0 8 * * *"),
        report_schedule=env.get("REPORT_SCHEDULE", "0 8 1 * *"),
    )

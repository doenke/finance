"""Mirror the OIDC profile picture locally (SSRF-safe, resized to 128x128 WebP)."""

import hashlib
import io
import logging
from urllib.parse import urlparse

import httpx
from PIL import Image

log = logging.getLogger("finanzen.avatar")

MAX_BYTES = 5 * 1024 * 1024
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}


def allowed_host(url: str, issuer: str, extra_hosts: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    hosts = {urlparse(issuer).hostname or ""} | set(extra_hosts)
    return parsed.hostname.lower() in {h.lower() for h in hosts if h}


def _download(url: str, token: str | None) -> bytes | None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=8.0, follow_redirects=False) as client:
        with client.stream("GET", url, headers=headers) as res:
            if res.status_code in (401, 403):
                return b"" if token is None else None
            if res.status_code != 200:
                return None
            data = bytearray()
            for chunk in res.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    return None
            return bytes(data)


def fetch_avatar(url: str, access_token: str | None, issuer: str, extra_hosts: tuple[str, ...]) -> tuple[bytes, str] | None:
    """Return (webp bytes, content hash) or None. Never raises."""
    try:
        if not allowed_host(url, issuer, extra_hosts):
            log.info("avatar host not allowed")
            return None
        raw = _download(url, None)
        if raw == b"" and access_token:
            raw = _download(url, access_token)
        if not raw:
            return None
        image = Image.open(io.BytesIO(raw))
        if image.format not in ALLOWED_FORMATS:
            return None
        image = image.convert("RGBA")
        side = min(image.size)
        left = (image.width - side) // 2
        top = (image.height - side) // 2
        image = image.crop((left, top, left + side, top + side)).resize((128, 128), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="WEBP", quality=85)
        data = out.getvalue()
        return data, hashlib.sha256(data).hexdigest()[:16]
    except Exception:  # noqa: BLE001 - a broken avatar must never break the login
        log.warning("avatar download failed", exc_info=False)
        return None

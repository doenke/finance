"""Run with `python -m finanzen`."""

import uvicorn

from .config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "finanzen.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=settings.trusted_proxy,
        forwarded_allow_ips="*" if settings.trusted_proxy else None,
        access_log=False,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()

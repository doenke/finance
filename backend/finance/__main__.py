"""Run with `python -m finance`."""

import uvicorn

from .config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "finance.main:app",
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()

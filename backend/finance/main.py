"""Application entry point. For now only the placeholder page and health checks."""

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .health import run_checks

settings = load_settings()
log = logging.getLogger("finance")

app = FastAPI(title="finance", version=settings.version, docs_url=None, redoc_url=None, openapi_url=None)

NO_STORE = {"Cache-Control": "no-store"}


@app.get("/healthz")
def healthz() -> JSONResponse:
    ok, checks = run_checks(settings)
    body = {"status": "ok" if ok else "error", "version": settings.version, "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503, headers=NO_STORE)


@app.get("/healthz/live")
def healthz_live() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": settings.version}, headers=NO_STORE)


@app.get("/api/version")
def version() -> JSONResponse:
    return JSONResponse({"version": settings.version}, headers=NO_STORE)


@app.get("/robots.txt", include_in_schema=False)
def robots() -> FileResponse:
    return FileResponse(settings.web_dir / "robots.txt", media_type="text/plain")


if settings.web_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
else:
    log.warning("web directory %s not found, serving API only", settings.web_dir)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response

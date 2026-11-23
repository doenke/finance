"""Application factory: API, auth, avatars, health checks and the SPA."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from . import cache
from .api.accounts import router as accounts_router
from .api.imports import admin as admin_router
from .api.imports import router as imports_router
from .api.performance import router as performance_router
from .api.prices import router as prices_router
from .api.routes import public as public_api
from .api.routes import router as api_router
from .auth.routes import router as auth_router
from .config import Settings, load_settings
from .db import get_db, make_engine, make_sessionmaker, run_migrations
from .health import run_checks
from .models import User

log = logging.getLogger("finanzen")
NO_STORE = {"Cache-Control": "no-store"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(settings: Settings | None = None, migrate: bool = True) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not settings.session_key:
        if not settings.dev_login:
            log.warning("SESSION_KEY is not set – logins will not survive a restart")
        import secrets

        settings = Settings(**{**settings.__dict__, "session_key": secrets.token_urlsafe(32)})
    if settings.dev_login:
        log.warning("DEV_LOGIN is active – never use this in production")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = None
        if settings.scheduler and settings.database_url:
            from .scheduler import start_scheduler

            scheduler = start_scheduler(settings, app.state.sessionmaker)
        yield
        if scheduler:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="finanzen", version=settings.version, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    if settings.database_url:
        if migrate:
            run_migrations(settings.database_url)
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # CSRF protection on top of SameSite=Lax: state-changing requests must come from our own origin.
        if request.method in UNSAFE_METHODS and request.url.path.startswith(("/api/", "/auth/logout")):
            origin = request.headers.get("origin")
            if origin and origin != settings.public_origin:
                return JSONResponse({"detail": "Ungültige Herkunft"}, status_code=403)
        response = await call_next(request)
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/") and response.status_code < 400:
            cache.bump()
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith(("/api/", "/auth/")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        ok, checks = run_checks(settings)
        body = {"status": "ok" if ok else "error", "version": settings.version, "checks": checks}
        return JSONResponse(body, status_code=200 if ok else 503, headers=NO_STORE)

    @app.get("/healthz/live")
    def healthz_live() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": settings.version}, headers=NO_STORE)

    @app.get("/avatar/{user_id}")
    def avatar(user_id: int, db: Session = Depends(get_db)) -> Response:
        user = db.get(User, user_id)
        if user is None or not user.avatar:
            return Response(status_code=404)
        return Response(
            user.avatar,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
        )

    app.include_router(auth_router)
    app.include_router(public_api)
    app.include_router(api_router)
    app.include_router(accounts_router)
    app.include_router(prices_router)
    app.include_router(performance_router)
    app.include_router(imports_router)
    app.include_router(admin_router)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(path: str) -> JSONResponse:
        return JSONResponse({"detail": "Nicht gefunden"}, status_code=404)

    mount_spa(app, settings.web_dir)
    return app


def mount_spa(app: FastAPI, web_dir: Path) -> None:
    """Serve the built SvelteKit app; unknown paths fall back to index.html (client-side routing)."""
    root = web_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if not root.is_dir():
            return JSONResponse({"detail": "Frontend nicht gebaut"}, status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            headers = {}
            if "/_app/immutable/" in f"/{path}":
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif candidate.suffix in {".html", ".js", ".json", ".webmanifest", ".css"}:
                headers["Cache-Control"] = "no-cache"
            return FileResponse(candidate, headers=headers)
        if path and "." in path.rsplit("/", 1)[-1]:
            return Response(status_code=404)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

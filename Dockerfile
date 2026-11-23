# syntax=docker/dockerfile:1

# --- web: build the SvelteKit app once, natively on the build platform ---
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
ARG APP_VERSION=dev
RUN APP_VERSION=$APP_VERSION npm run build

# --- build: install the backend and its dependencies into a virtualenv ---
FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY backend/pyproject.toml /src/backend/pyproject.toml
COPY backend/finanzen /src/backend/finanzen
RUN /venv/bin/pip install /src/backend

# --- runtime: slim image, non-root user ---
FROM python:3.13-slim
RUN groupadd --system --gid 10001 finanzen \
 && useradd --system --uid 10001 --gid finanzen --home-dir /nonexistent --shell /usr/sbin/nologin finanzen \
 && mkdir -p /data && chown finanzen:finanzen /data
COPY --from=build /venv /venv
COPY --from=web /web/build /app/web

ENV PATH=/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PORT=43651 \
    DATA_DIR=/data \
    WEB_DIR=/app/web \
    TZ=Europe/Berlin

USER finanzen
WORKDIR /app
VOLUME ["/data"]
EXPOSE 43651

# /healthz answers 200 only if the database and the data directory are fine.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)" || exit 1

# Declared late so a new version does not invalidate the layer cache above.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.title="finanzen" \
      org.opencontainers.image.description="Finanzüberblick für den Haushalt" \
      org.opencontainers.image.source="https://github.com/doenke/finance" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version=$APP_VERSION

CMD ["python", "-m", "finanzen"]

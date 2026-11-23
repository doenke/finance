# finanzen – Hinweise für Claude

Finanzüberblick für den Haushalt (Konten, Depots, weitere Anlagen, Rendite).
Anforderungen: `docs/ANFORDERUNGEN.md` – vor neuen Funktionen lesen und bei
Entscheidungen dort mitpflegen.

## Aufbau

- `backend/` – Python 3.13, FastAPI (`finanzen/`), Tests unter `tests/` (pytest).
  Start: `python -m finanzen`. Konfiguration nur über Env (`finanzen/config.py`).
- `web/` – Frontend. Derzeit eine statische Platzhalterseite mit Manifest und
  Icons (aus `icon.svg`/`icon-maskable.svg` erzeugt). Wird später durch ein
  SvelteKit-Build ersetzt, das das Backend ausliefert.
- `Dockerfile` – mehrstufig, läuft als UID 10001, `HEALTHCHECK` gegen `/healthz`.
- `compose.example.yml`, `.env.example` – Betriebsvorlagen (Port 43651,
  Mounts unter `/data/container/finanzen/...`, Postgres ohne Port-Freigabe).
- `.github/workflows/ci.yml` – Version, Tests, Smoke-Test des Images, Push
  nach `ghcr.io/doenke/finanzen` (latest nur von `main`).

## Regeln

- UI-Texte, README und Doku auf Deutsch; Code, Bezeichner, Kommentare Englisch.
- Beträge immer als `Decimal`/`NUMERIC`, nie als Float.
- Keine externen Ressourcen im Frontend (keine CDNs, keine Webfonts).
- Secrets nur über `.env`; Bank-PINs nie loggen oder zurückgeben.
- `/healthz`: JSON `{status, version, checks}`, 200/503, `Cache-Control: no-store`,
  keine Hostnamen oder Stacktraces. Der Service Worker cacht `/healthz`, `/api/`
  und `/auth/` nie.
- README bei jeder Funktionsänderung mitpflegen (Stil: duzen, Nutzen zuerst,
  Abschnittsfolge beibehalten). `.env.example` und `compose.example.yml`
  ebenso.

## Versionierung x.yy.zzz

`versions.json` + `scripts/version.mjs`: x = `major` von Hand, yy = Tage mit
Änderungen an `paths` seit `since` (Europe/Berlin, aus der Git-Historie), zzz =
CI-Lauf. CI braucht `fetch-depth: 0`. Neue App-Ordner in `paths` aufnehmen.
Die Version steht in der App und in `/healthz`. Nach einem Push die Version
aus der CI-Zusammenfassung nennen.

## Verifikation

```bash
cd backend && pip install -e ".[test]" && python -m pytest -q
```

Mit Datenbank zusätzlich `TEST_DATABASE_URL=postgresql://…` setzen. Docker:
`docker compose config -q`, Container wird `healthy`, `/healthz` liefert 200
mit Version und bei gestoppter DB 503.

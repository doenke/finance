# finanzen – Hinweise für Claude

Finanzüberblick für den Haushalt (Konten, Depots, weitere Anlagen, Rendite).
Anforderungen: `docs/ANFORDERUNGEN.md` – vor neuen Funktionen lesen und bei
Entscheidungen dort mitpflegen.

## Aufbau

- `backend/` – Python 3.13, FastAPI (`finanzen/`), Tests unter `tests/` (pytest).
  Start: `python -m finanzen`. Konfiguration nur über Env (`finanzen/config.py`).
- `backend/finanzen/` – `main.py` (App-Factory `create_app`, SPA-Auslieferung,
  CSRF-Origin-Prüfung), `auth/` (OIDC mit PKCE, Session-Cookie, Avatare,
  `DEV_LOGIN`), `api/` (JSON-API unter `/api`), `models.py` + `migrations/`
  (Alembic, laufen beim Start). Neue Tabellen immer per neuer Migration.
  `services/`: `valuation.py` (Wert zum Stichtag), `series.py` (tägliche
  Wertreihen und Zahlungsströme je Kontoart), `returns.py` (TTWROR mit
  Zahlungen am Tagesende, XIRR), `performance.py` (Aggregation, Cache über
  `cache.py`, jede schreibende API-Anfrage verwirft ihn), `prices/`
  (Kursquellen-Adapter: onvista als Standard, Yahoo; Fallback auf onvista per ISIN in `sync.py`), `fx.py` (EZB), `sync.py`, `loan.py`,
  `csvimport.py`, `backup.py` (JSON-Sicherung/-Wiederherstellung, auch CLI
  `python -m finanzen backup|restore`). Hintergrundjobs in `scheduler.py`.
  MCP: `mcp/oauth.py` (OAuth-2.1-Autorisierung mit DCR, PKCE, Zustimmungsseite;
  `/api/mcp/clients` für die Einstellungen) und `mcp/server.py` (JSON-RPC unter
  `/mcp`, Werkzeuge nutzen die Funktionen aus `api/`; nur lesen und anlegen,
  nichts löschen).
  FinTS: `services/fints_sync.py` – jeder Abruf ist ein Job in einem Thread,
  der den Dialog offen hält und auf TAN/Auswahl wartet (vorher immer
  `db.commit()`, nie eine Transaktion offen halten). Der Bank-Client kommt
  über `app.state.fints_factory`, Tests nutzen einen Fake-Client
  (`tests/test_fints.py`). `Bank` (BLZ, Adresse) ist gemeinsam, `BankLogin`
  gehört einem User (`user_id`), nur der Besitzer ruft ab. PINs: `secrets.py` (AES-GCM, Kontext pro Login).
- `web/` – SvelteKit **3** (SPA, adapter-static, Svelte 5 Runes). Achtung,
  Kit 3 unterscheidet sich von Kit 2: Konfiguration in `vite.config.ts`
  (`sveltekit({...})`, kein `svelte.config.js`), Imports über `#lib/…` mit
  Dateiendung für `.ts` (`#lib/api.ts`), Service Worker nutzt `$app/manifest`,
  `$app/env`, `$app/service-worker`. tsconfig erweitert `$app/tsconfig`.
  Statische Dateien und Icons in `web/static/`. Web Share Target: `manifest.webmanifest` → POST `/import/teilen`, der Service Worker legt die Datei im Cache `finanzen-share` ab, `/import?geteilt=1` holt sie (ohne SW leitet das Backend auf `?geteilt=fehler`). Prüfen: `npm run check`,
  bauen: `npm run build` (nach `web/build`, das Backend liefert es aus).
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
cd web && npm ci && npm run check && npm run build
```

Lokal entwickeln: Backend mit `DEV_LOGIN=true DATABASE_URL=… python -m finanzen`,
Frontend mit `npm run dev` (Vite leitet `/api`, `/auth`, `/avatar` an Port 43651).

Mit Datenbank zusätzlich `TEST_DATABASE_URL=postgresql://…` setzen. Docker:
`docker compose config -q`, Container wird `healthy`, `/healthz` liefert 200
mit Version und bei gestoppter DB 503.

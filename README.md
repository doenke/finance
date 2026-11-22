<img src="web/icon-192.png" alt="" width="96" height="96">

# finance 📈

finance ist der Finanzüberblick für euren Haushalt: das Girokonto bei der
Sparkasse, das Tagesgeld bei der DKB, das Depot bei Trade Republic, die
STAK-Anteile vom Arbeitgeber, die Wohnung samt Kredit und der Goldbarren im
Schrank – alles an einem Ort, mit Verlauf und ehrlicher Rendite.

Kurz gesagt: einmal reinschauen und wissen, wo ihr steht – und ob euer Depot
besser läuft als der MSCI World.

> **Stand:** Grundgerüst. Die App startet, zeigt eine Platzhalterseite und
> meldet über `/healthz`, ob alles läuft. So lassen sich DNS, Proxy, Firewall
> und Docker schon einrichten. Die eigentlichen Funktionen kommen Schritt für
> Schritt – was geplant ist, steht in [docs/ANFORDERUNGEN.md](docs/ANFORDERUNGEN.md).

| Dashboard | Depot | Benchmark |
| --- | --- | --- |
| *Screenshot folgt* | *Screenshot folgt* | *Screenshot folgt* |

## Was finance für dich machen wird

- **Alles in einer Summe** – Konten, Depots, Immobilien, Krypto, Gold,
  Altersvorsorge und Kredite ergeben euer Nettovermögen, mit Verlauf über die
  Jahre.
- **Rendite, die stimmt** – zeitgewichtet (TTWROR) und geldgewichtet (IZF),
  damit Sparpläne und Entnahmen das Ergebnis nicht verfälschen.
- **Direkt von der Bank** – Sparkasse, DKB und OLB per FinTS; Trade Republic,
  die Bitcoins bei BSDEX und die Advanzia-Kreditkarte per Import.
- **Kurse von selbst** – täglich über Yahoo Finance, weitere Anbieter lassen
  sich später zuschalten.
- **Für den ganzen Haushalt** – jede Person meldet sich selbst an, Konten
  gehören einer Person oder euch gemeinsam.
- **Für sich bleiben** – läuft auf eurem eigenen Server, keine Cloud, kein
  Tracking. Bank-PINs werden nur gespeichert, wenn du das willst, und dann
  verschlüsselt.
- **Als App installieren** – finance ist eine PWA und funktioniert auf dem
  Handy wie eine App.

## Für wen ist das?

finance passt zu dir, wenn du ...

- Konten und Depots bei mehreren Banken hast und den Überblick in einer
  Tabelle satt bist,
- wissen willst, was dein Depot wirklich bringt – nicht nur „+12 %“,
- auch Dinge wie Immobilien, Mitarbeiterbeteiligungen oder Gold mitzählen willst,
- selbst hostest und deine Finanzdaten nicht bei einem Fremden ablegen willst.

## Schnellstart mit Docker

Auf garageband die Ordner anlegen – das Datenverzeichnis gehört dem Benutzer
im Container (UID 10001):

```bash
sudo mkdir -p /data/container/finance/data /data/container/finance/db
```

```bash
sudo chown 10001:10001 /data/container/finance/data
```

Vorlagen kopieren:

```bash
cp .env.example .env
```

```bash
cp compose.example.yml compose.yml
```

In `.env` für den Anfang nur `PUBLIC_URL` und `POSTGRES_PASSWORD` ausfüllen
(`openssl rand -hex 32`), dann:

```bash
docker compose up -d
```

```bash
docker compose ps
```

`finance` und `finance-db` zeigen nach ein paar Sekunden „healthy“. Die App
lauscht auf Port **43651** (innen und außen gleich), das Image ist
`ghcr.io/doenke/finance:latest`.

## Ein erster Rundgang

### 1. Seite öffnen

Unter `https://finance.kanonenwiese.de` erscheint die Platzhalterseite mit
Version und dem Zustand von Datenbank und Datenverzeichnis. Steht dort alles
auf „ok“, sind DNS, Proxy und Container richtig eingerichtet.

### 2. Zum Startbildschirm hinzufügen

Im Browsermenü „Zum Startbildschirm hinzufügen“ bzw. „App installieren“
wählen – das Icon ist schon da.

## Kleine Konfiguration, große Wirkung

| Einstellung | Wofür? |
| --- | --- |
| `PUBLIC_URL` | Öffentliche Adresse, z. B. `https://finance.kanonenwiese.de` |
| `POSTGRES_PASSWORD` | Passwort der Datenbank (nur Buchstaben und Ziffern) |
| `SESSION_KEY` | Signiert die Anmeldung – ab der Version mit Login |
| `SECRETS_KEY` | Verschlüsselt gespeicherte Bank-PINs – **nie ändern, gut aufheben** |
| `OIDC_*` | Anmeldung über Pocket ID – ab der Version mit Login |
| `FINTS_PRODUCT_ID` | Registrierungsnummer für FinTS – ab der Bankanbindung |

Alle Werte mit Erklärung stehen in [.env.example](.env.example). Was dort
schon drinsteht, aber noch nicht genutzt wird, ist entsprechend markiert.

---

## Betriebsecke

### Reverse Proxy (z. B. Nginx Proxy Manager)

Einen Proxy Host `finance.kanonenwiese.de` auf `http://garageband:43651`
anlegen, dann:

- **Force SSL** einschalten – ohne HTTPS keine installierbare App und keine
  sichere Anmeldung.
- **HTTP/2** und **HSTS** dürfen an.

Für DNS und Firewall gibt es den n8n-Provisioning-Workflow (Name `finance`,
Port `43651`).

### Wichtige Hinweise für den Betrieb

- **Healthcheck:** `https://finance.kanonenwiese.de/healthz` – 200 mit
  Version, wenn Datenbank und Datenverzeichnis passen, sonst 503 mit dem
  betroffenen Teil. Gut für Uptime Kuma. `/healthz/live` meldet nur, dass der
  Prozess läuft.
- **Version:** steht auf der Seite und in `/healthz`, Schema x.yy.zzz.
- **Updates:** `docker compose pull && docker compose up -d`.
- **Backup:** Bis die App ihre eigene tägliche Sicherung hat, reicht ein
  `pg_dump` der Datenbank:

  ```bash
  docker exec finance-db pg_dump -U finance finance | gzip > finance-$(date +%F).sql.gz
  ```

- **Image privat?** Ist das Paket auf ghcr.io privat, auf garageband einmal
  `docker login ghcr.io` mit einem Token (Scope `read:packages`) ausführen
  oder das Paket in GitHub auf „public“ stellen.
- **`SECRETS_KEY`** nach dem ersten Speichern einer PIN nie mehr ändern und
  getrennt vom Backup aufbewahren.

## Lizenz

[MIT](LICENSE)

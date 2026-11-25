<img src="web/static/icon-192.png" alt="" width="96" height="96">

# Finanzen 📈

Finanzen ist der Finanzüberblick für euren Haushalt: das Girokonto bei der
Sparkasse, das Tagesgeld bei der DKB, das Depot bei Trade Republic, die
STAK-Anteile vom Arbeitgeber, die Wohnung samt Kredit und der Goldbarren im
Schrank – alles an einem Ort, mit Verlauf und ehrlicher Rendite.

Kurz gesagt: einmal reinschauen und wissen, wo ihr steht – und ob euer Depot
besser läuft als der MSCI World.

> **Stand:** Konten, Depots, alle Anlageformen, Tilgungsplan, tägliche Kurse,
> Rendite, Dashboard mit Benchmark, Bankanbindung per FinTS, CSV-Import (Bank
> und Portfolio Performance), Export, tägliche Sicherung, Haltefrist für
> Krypto, Privatmodus, Benachrichtigungen sowie Verträge & Abos sind fertig.
> Als Nächstes: der Budget-Planer – siehe [docs/ANFORDERUNGEN.md](docs/ANFORDERUNGEN.md).

| Übersicht | Depot | Kredit | Konten |
| --- | --- | --- | --- |
| ![Nettovermögen mit Verlauf, Aufteilung nach Anlageklasse und Person](docs/screenshots/dashboard.png) | ![Depot mit Rendite im Vergleich zum MSCI World](docs/screenshots/depot.png) | ![Tilgungsplan mit Restschuld, Zinsen und Sondertilgungen](docs/screenshots/kredit.png) | ![Konten gruppiert nach Anlageklasse mit Personenfilter](docs/screenshots/konten.png) |

<sub>Screenshots mit Beispieldaten.</sub>

## Was Finanzen für dich machen wird

- **Alles in einer Summe** – Konten, Depots, Immobilien, Krypto, Gold,
  Altersvorsorge und Kredite ergeben euer Nettovermögen, mit Verlauf über die
  Jahre.
- **Rendite, die stimmt** – zeitgewichtet (TTWROR) und geldgewichtet (IZF),
  damit Sparpläne und Entnahmen das Ergebnis nicht verfälschen.
- **Direkt von der Bank** – Sparkasse, DKB und OLB per FinTS; Trade Republic
  und die Advanzia-Kreditkarte per CSV-Import, die Bitcoins bei BSDEX per
  eigenem Import.
- **Kurse von selbst** – täglich über onvista oder Yahoo Finance, per ISIN,
  mit automatischer Ausweichquelle.
- **Für den ganzen Haushalt** – jede Person meldet sich selbst an, Konten
  gehören einer Person oder euch gemeinsam.
- **Für sich bleiben** – läuft auf eurem eigenen Server, keine Cloud, kein
  Tracking. Bank-PINs werden nur gespeichert, wenn du das willst, und dann
  verschlüsselt.
- **Als App installieren** – Finanzen ist eine PWA und funktioniert auf dem
  Handy wie eine App.

## Für wen ist das?

Finanzen passt zu dir, wenn du ...

- Konten und Depots bei mehreren Banken hast und den Überblick in einer
  Tabelle satt bist,
- wissen willst, was dein Depot wirklich bringt – nicht nur „+12 %“,
- auch Dinge wie Immobilien, Mitarbeiterbeteiligungen oder Gold mitzählen willst,
- selbst hostest und deine Finanzdaten nicht bei einem Fremden ablegen willst.

## Schnellstart mit Docker

Auf garageband die Ordner anlegen – das Datenverzeichnis gehört dem Benutzer
im Container (UID 10001):

```bash
sudo mkdir -p /data/container/finanzen/data /data/container/finanzen/db
```

```bash
sudo chown 10001:10001 /data/container/finanzen/data
```

Vorlagen kopieren:

```bash
cp .env.example .env
```

```bash
cp compose.example.yml compose.yml
```

In `.env` mindestens `PUBLIC_URL`, `POSTGRES_PASSWORD` (`openssl rand -hex 32`),
`SESSION_KEY` (`openssl rand -base64 32`), `OIDC_ISSUER` und `OIDC_CLIENT_ID`
ausfüllen (siehe „Login über OIDC“ unten), dann:

```bash
docker compose up -d
```

```bash
docker compose ps
```

`finanzen` und `finanzen-db` zeigen nach ein paar Sekunden „healthy“. Die App
lauscht auf Port **43651** (innen und außen gleich), das Image ist
`ghcr.io/doenke/finanzen:latest`.

## Ein erster Rundgang

### 1. Anmelden

`https://finanzen.kanonenwiese.de` öffnen und auf „Mit Kanonenwiese SSO
anmelden“ tippen. Wer sich zum ersten Mal anmeldet, landet automatisch im
Haushalt – mit Vornamen und Profilbild aus Pocket ID.

### 2. Haushalt vervollständigen

Unter **Haushalt** (am Handy über Optionen) steht jede Person, die sich schon einmal angemeldet hat.
Kinder oder andere Personen ohne eigenen Login legst du dort mit „+ Person“ an,
damit du ihnen später Konten und Anlagen zuordnen kannst. Jede Person bekommt
eine Farbe, die später in Diagrammen wieder auftaucht.

### 3. Konten und Anlagen anlegen

Unter **Konten** legst du mit „+ Konto“ alles an, was Wert hat – oder kostet:

- **Girokonto, Tagesgeld, Kreditkarte:** einen Kontostand zu einem Stichtag
  eintragen, spätere Umsätze werden darauf gerechnet. Ein Stand im Monat
  reicht auch.
- **Depot, Krypto, STAK-Anteile, Edelmetalle:** Käufe, Verkäufe und
  Dividenden als Transaktionen erfassen, Bestand und Einstand (FIFO) rechnet
  Finanzen selbst. Für STAK-Zertifikate trägst du den festgesetzten Kurs je
  Periode beim Wertpapier ein; er gilt bis zum nächsten Eintrag. Beim Gold
  zählt der Feingehalt mit.
- **Immobilie, Altersvorsorge, Sonstiges:** Schätzwert oder Wert aus der
  Standmitteilung zu Stichtagen, dazu Beiträge oder Mieteinnahmen.
- **Festgeld:** Betrag, Zins und Laufzeit – der Wert wird bis zur Fälligkeit
  aufgezinst.
- **Kredit:** Darlehensbetrag, Zins, Tilgung oder Rate und erste Rate – daraus
  entsteht der **Tilgungsplan** mit Restschuld zum Ende der Zinsbindung,
  Zinsen bisher und noch, Schuldenfrei-Datum und CSV-Export. Geplante
  Sondertilgungen (z. B. jedes Jahr im Dezember) fließen ein, das
  Sondertilgungsrecht wird überwacht. Trägst du die Restschuld aus dem
  Kontoauszug ein, rechnet der Plan ab dort weiter.
  Hat sich die Rate geändert – oder wird sie es? Unter **Ratenänderungen**
  trägst du ab einem Datum die neue Rate ein, auch rückwirkend; Restschuld,
  Verlauf und Szenarien rechnen damit. Hat die Bank dafür (oder für etwas
  anderes) eine Gebühr auf den Kredit geschlagen, trägst du sie unter
  **Gebühren** ein – sie erhöht die Restschuld ab diesem Tag und wird mit
  abgezahlt.
  Unter **Szenarien** spielst du durch, was wäre, wenn: geplante oder
  zusätzliche Sondertilgungen, eine höhere Rate ab einem Stichtag oder ein
  anderer Zins nach der Zinsbindung. Bis zu vier Varianten stehen neben dem
  Plan ohne Sondertilgungen – mit Schuldenfrei-Datum, Restschuld zum Ende der
  Zinsbindung, Zinsersparnis und wie viel früher ihr fertig seid.

**Kurse:** Beim Anlegen eines Wertpapiers suchst du es per ISIN oder Name –
standardmäßig bei **onvista**, das Aktien, ETFs, Fonds, Anleihen, Krypto und
Edelmetalle kennt und gleich einen Euro-Handelsplatz (Xetra, Tradegate, …)
wählt. Yahoo Finance gibt es weiter als Alternative (z. B. `EUNL.DE`); blockiert
Yahoo, springt onvista über die ISIN automatisch ein. Unter **Einstellungen**
stellst du alle bisherigen Yahoo-Wertpapiere mit einem Klick auf onvista um.
Die Historie ab dem ersten Kauf wird sofort geladen, danach kommt jeden
Werktag um 23:30 Uhr der Schlusskurs dazu. Kurse, die älter als drei
Handelstage sind, werden als „veraltet“ markiert.

Jedes Konto gehört einer Person oder mehreren mit Anteilen. Oben in der
Kontenliste filterst du nach Person – gemeinsame Konten zählen dann mit dem
jeweiligen Anteil.

### 4. Wissen, wo ihr steht

Die **Übersicht** zeigt euer Nettovermögen, die Veränderung seit Vormonat und
Jahresbeginn, den Verlauf und die Aufteilung nach Anlageklasse und Person.
Darunter steht die Rendite eurer Anlagen – als **TTWROR** (wie gut die
Anlagen selbst gelaufen sind, egal wann ihr Geld eingezahlt habt) und als
**IZF** (eure persönliche Rendite pro Jahr, mit Timing). Wähl einen
Vergleichswert, etwa einen MSCI-World-ETF, und Finanzen legt dessen Verlauf
daneben. Dieselbe Auswertung gibt es für jedes einzelne Konto und Depot, mit
allen Zeiträumen von einem Monat bis „seit Beginn“.

**Verfügbar und gebunden** trennt, was ihr kurzfristig nutzen könntet –
sofort auf den Haushaltskonten (abzüglich Kreditkarten) oder angelegt in
Tagesgeld, Depots, Krypto und Edelmetallen –, von
dem, was festliegt (Festgeld, Altersvorsorge, Immobilien, Beteiligungen,
sonstige Anlagen) – mit dem Datum, ab dem es frei wird: Fälligkeit beim
Festgeld, Rentenbeginn bei der Altersvorsorge oder ein eigenes „frei ab“.
Passt die Einteilung bei einem Konto nicht, stellst du sie unter
„Bearbeiten“ → Verfügbarkeit um. Depots und Krypto klappst du auch hier auf
und siehst jede Position mit Stückzahl, aktuellem Wert und Gewinn in Prozent.

Darunter zeigt **Rendite je Anlage**, was welche Anlage bringt – sortiert
nach IZF pro Jahr, mit TTWROR und Gewinn daneben – und woraus sich eure
Gesamtrendite zusammensetzt: Jede Anlage steuert ihren Gewinn in Euro und in
Prozentpunkten bei, die Balken addieren sich zur Gesamtrendite des gewählten
Zeitraums (Standard: ein Jahr). Depots und Krypto klappst du auf: Dann
siehst du die Rendite jeder einzelnen Position, und in der Zusammensetzung
stehen die Positionen statt des Depots.

So rechnet Finanzen:

- Käufe, Verkäufe, Beiträge und Einzahlungen sind Ein- und Auszahlungen und
  zählen nicht als Gewinn. Dividenden, Zinsen und Kursgewinne schon.
- Umbuchungen innerhalb des Haushalts – Girokonto aufs Depot – heben sich in
  der Gesamtsicht auf.
- Bei Immobilien und Altersvorsorge gilt zwischen zwei Bewertungen der letzte
  Wert plus die Beiträge seither.
- Kredite stecken im Nettovermögen, aber nicht in der Rendite.

**Haltefrist bei Krypto und Gold:** Im Krypto- oder Edelmetall-Konto siehst
du je Coin, wie viel du schon steuerfrei verkaufen könntest (gehalten länger
als ein Jahr, § 23 EStG), was noch in der Frist steckt und wann der nächste
Kaufposten frei wird. Gerechnet wird nach FIFO. Dazu kommen deine Verkäufe
nach Jahr – getrennt in steuerpflichtig und steuerfrei, mit Hinweis auf die
Freigrenze von 1.000 €.

**Positionen im Vergleich:** In jedem Depot (und unter `/wertpapiere` für
alle Depots zusammen) vergleichst du die einzelnen Wertpapiere: Kursverlauf
aller Positionen ab gleichem Start, Gewichtung, Rendite gegen Schwankung als
Streudiagramm, eine Kennzahlentabelle (1 Monat bis 5 Jahre, Schwankung,
größter Rückgang) und eine Korrelations-Matrix, die zeigt, wie gut die
Positionen das Risiko streuen. Kurse lädt Finanzen dafür mindestens fünf
Jahre zurück – auch wenn du ein Wertpapier erst seit Kurzem hast.

### 5. Bank verbinden (FinTS)

Unter **Banken** legst du mit „+ Bank“ Sparkasse, DKB, OLB & Co. an:
Bankleitzahl und FinTS-Adresse gelten für den ganzen Haushalt, dazu kommt
dein eigener Zugang mit dem Anmeldenamen wie im Online-Banking. Hat schon
jemand die Bank angelegt, fügst du dort nur noch „Mein Zugang“ hinzu. Jede
Person sieht nur ihre eigenen Zugangsdaten und ruft nur mit ihrem eigenen
Zugang ab – die abgerufenen Konten sehen alle. Finanzen fragt dann nach der PIN, lässt dich das
TAN-Verfahren wählen und zeigt die Konten, die die Bank kennt. Du
entscheidest je Konto: neu anlegen, mit einem vorhandenen verknüpfen oder
weglassen.

- **Aktualisieren** holt Salden, Umsätze (beim ersten Mal 90 Tage) und
  Depotbestände. Verlangt die Bank eine TAN, erscheint sie im Dialog –
  pushTAN und App-Freigaben bestätigst du einfach in der Banking-App,
  photoTAN scannst du vom Bildschirm, beim chipTAN gibst du die TAN aus der
  manuellen Eingabe ein (Flickercode wird nicht angezeigt).
- **PIN speichern** ist freiwillig. Ohne gespeicherte PIN fragt Finanzen bei
  jedem Abruf. Mit gespeicherter PIN (verschlüsselt mit `SECRETS_KEY`) kann
  Finanzen jede Nacht selbst abrufen; braucht die Bank alle 90 Tage eine
  TAN-Freigabe, siehst du unter Banken einen Hinweis.
- **Depots:** Beim ersten Abruf übernimmt Finanzen den Bestand zum
  Einstandskurs laut Bank. Später zeigt es Abweichungen zwischen Bank und
  deinen Transaktionen – meist fehlt ein Kauf – und bucht sie auf Wunsch als
  Ein- oder Auslieferung.

### 6. Umsätze und Depots importieren

Unter **Konten → Import** liest Finanzen den CSV-Export deiner Bank
(Sparkasse „CSV-CAMT“, DKB, OLB, …), Exporte aus **Portfolio
Performance** und die Transaktionsliste von **BSDEX**. Bei BSDEX landen
ausgeführte Käufe und Verkäufe im Krypto-Depot, Einzahlungen und der
Euro-Anteil jeder Order auf dessen Verrechnungskonto – so stimmen Bitcoin-Bestand,
Einstand inklusive Gebühren und das Euro-Guthaben bei der Börse. Du siehst vorher, was neu ist, was schon da ist und was nicht
passt. Spaltenzuordnungen speicherst du als Vorlage, doppelte Buchungen
werden übersprungen, und jeder Import lässt sich mit einem Klick komplett
rückgängig machen. Beim Portfolio-Performance-Import werden fehlende
Wertpapiere gleich mit angelegt – samt Kurshistorie ab dem ersten Kauf.

**Direkt teilen:** Ist Finanzen auf dem Android-Handy installiert, taucht es
im Teilen-Menü auf. Teile die CSV aus der Banking-App, von BSDEX oder aus
der Dateien-App an Finanzen – die Importseite öffnet sich mit der Datei,
erkennt, ob sie von der Bank, aus Portfolio Performance oder von BSDEX
stammt, und wählt das passende Konto vor, wenn es nur eins gibt. (iPhone
und iPad unterstützen das Teilen an Web-Apps leider nicht; dort wählst du
die Datei auf der Importseite aus.)

### 7. Verträge und Abos im Blick

Unter **Verträge** sucht Finanzen in euren Umsätzen nach Zahlungen, die
regelmäßig wiederkommen – Miete, Strom, Versicherungen, Netflix, der Kredit,
das Gehalt, die Sparrate. Es erkennt wöchentliche bis jährliche Zahlungen,
auch wenn mal ein Monat fehlt, und trennt Abos, die über PayPal laufen,
ebenso Gehalt und Spesen vom selben Arbeitgeber.
Jeder Vorschlag kommt mit einer Kategorie; du übernimmst ihn, änderst Name
oder Kategorie oder ignorierst ihn.

Geld zwischen euren eigenen Konten gehört in die Kategorie **Umbuchungen**:
Die zählt nirgends mit – weder als Einnahme noch als Ausgabe noch als
Sparrate. Überweisungen an eine eigene IBAN oder an euren eigenen Namen
schlägt Finanzen dort automatisch vor. Sparpläne, Riester und Co. stehen
unter **Sparen & Anlegen** und zählen als Sparrate.

Die Übersicht zeigt dann eure Fixkosten im Monat, die regelmäßigen
Einnahmen, die Sparraten und was frei bleibt, die Kosten nach Kategorie und
was in den nächsten 30 Tagen fällig ist. Finanzen markiert, wenn ein Betrag
sich geändert hat (Preiserhöhung) oder eine Zahlung ausbleibt (gekündigt?).
Die Kategorie landet auch an den einzelnen Umsätzen – die Grundlage für den
späteren Budget-Planer. Am besten holst du vorher ein Jahr Umsätze ab, dann
findet Finanzen auch die jährlichen Zahlungen.

**Monatsbilanz:** Neben den Verträgen zeigt die **Monatsbilanz** aus euren
echten Buchungen, was jeden Monat reinkam, rausging und gespart wurde – als
Balken für die letzten zwölf Monate und im Detail je Monat: Ausgaben nach
Kategorie, Einnahmen und wohin gespart wurde (z. B. „DKB Girokonto → DKB
Tagesgeld“). Ein Klick auf eine Kategorie, eine Einnahme oder ein Sparziel
zeigt die einzelnen Buchungen dahinter – mit Empfänger, Verwendungszweck und
Konto. Passt eine Kategorie nicht, wählst du direkt in der Zeile eine andere;
das gilt nur für diese Buchung und schlägt Regeln und die automatische
Erkennung. „Automatisch“ nimmt die Festlegung wieder zurück. Ganz unten stehen
**alle Buchungen** des gewählten Monats – durchsuchbar, filterbar nach
Ausgaben, Einnahmen, Gespartem, Umbuchungen oder „Ohne Kategorie“ und mit
derselben Kategorie-Auswahl je Zeile. Dafür hat jedes Konto eine Rolle: **Alltag** (Girokonten,
Kreditkarte) als **Haushaltskonto** oder (Tagesgeld, Depots,
Verrechnungskonten) als **Sparkonto**. Gespart ist, was von Haushalts- auf
Sparkonten fließt, abzüglich Entnahmen, plus direkte Sparbeiträge wie Riester
oder Sparpläne. Geld zwischen Konten derselben Art zählt nicht. Welche Konten
Haushaltskonten sind, stellst du unter **Konten** ganz unten um.

**Jahresbilanz:** Daneben fasst die **Jahresbilanz** zusammen, was über einen
längeren Zeitraum reinkam, rausging und gespart wurde – seit Jahresbeginn, für
die letzten zwölf abgeschlossenen Monate oder für ein ganzes Kalenderjahr.
Jede Summe steht mit dem Monatsdurchschnitt und im Vergleich zum selben
Zeitraum ein Jahr vorher da (seit Jahresbeginn: bis zum selben Tag). Die
Kategorien zeigen Summe, Ø pro Monat, Vorjahr und Veränderung; ein Klick
öffnet die Buchungen dahinter, auch hier mit Kategorie-Auswahl je Buchung.

**Kategorien per Regel:** Bekannte Händler (REWE, Aldi, dm, Lieferando,
Amazon, Geldautomat …) ordnet Finanzen selbst zu. Für den Rest zeigt die
Monatsbilanz die häufigsten Ausgaben ohne Kategorie – ein Tipp auf
„Kategorie festlegen“ legt eine Regel an („enthält kiosk → Lebensmittel“),
mit Vorschau, welche Buchungen sie trifft. Regeln gelten auch für alle
künftigen Buchungen; du kannst sie auf Empfänger, Verwendungszweck, Ein- oder
Ausgaben und ein Konto beschränken.

### 8. Zum Startbildschirm hinzufügen

Im Browsermenü „Zum Startbildschirm hinzufügen“ bzw. „App installieren“
wählen. Unter **Einstellungen** schaltest du zwischen hell, dunkel und
„wie das System“ um.

**Privatmodus:** Das Auge oben auf der Übersicht (am Rechner in der
Seitenleiste) macht alle Beträge unkenntlich – praktisch, wenn du jemandem
etwas auf dem Handy zeigst. Prozente bleiben sichtbar. Die Einstellung gilt
nur auf diesem Gerät.

**Benachrichtigungen:** Unter **Einstellungen** schaltest du Push für dein
Gerät ein und wählst je Ereignis Push und/oder E-Mail:

- Bankabruf fehlgeschlagen oder TAN-Freigabe nötig (nur für deinen Zugang)
- Festgeld oder Zinsbindung läuft aus (Standard: 30 Tage vorher)
- Nettovermögen ändert sich stark (an einem Tag oder in einer Woche, ab
  einem Prozentsatz oder Betrag)
- Bewertung fällig: Rentenstand, Immobilienwert oder STAK-Kurs ist älter als
  13 Monate
- **Monatsbericht** per E-Mail am 1.: Nettovermögen, Veränderung, Rendite im
  Monat und seit Jahresbeginn, größte Bewegungen

E-Mails – auch der Monatsbericht – sind am Anfang ausgeschaltet; du
schaltest sie je Ereignis selbst ein. Push braucht einmalig ein Schlüsselpaar
in der `.env` (siehe unten), E-Mail die SMTP-Werte. Auf iPhone und iPad kommt Push nur in der installierten App
an (über „Zum Home-Bildschirm“).

### 9. Mit Claude verbinden (MCP)

Finanzen hat einen eingebauten MCP-Server. Damit kann Claude (oder ein
anderer Assistent mit MCP) deine Konten lesen und für dich Dinge eintragen –
zum Beispiel einen Rentenvertrag aus dem PDF-Kontoauszug anlegen, Stände
nachtragen oder Käufe buchen. Löschen kann der Assistent nichts.

1. In Claude unter **Einstellungen → Connectors → Eigenen Connector
   hinzufügen** die Adresse `https://finanzen.kanonenwiese.de/mcp`
   eintragen (steht auch unter **Einstellungen → KI-Assistenten** zum
   Kopieren).
2. Beim Verbinden meldest du dich wie gewohnt über Pocket ID an und
   bestätigst den Zugriff.
3. Fertig – Claude arbeitet mit deinem Namen. Unter **Einstellungen** siehst
   du, welche Assistenten verbunden sind, und kannst sie jederzeit trennen.

Es braucht keine weitere Konfiguration: Anmeldung, Registrierung des
Assistenten und Tokens (OAuth 2.1 mit PKCE) erledigt Finanzen selbst.

## Login über OIDC

Finanzen hat keine eigenen Passwörter – angemeldet wird über Pocket ID.

1. In Pocket ID einen OIDC-Client **finanzen** anlegen.
2. Callback-URL: `https://finanzen.kanonenwiese.de/auth/callback`
3. **Public Client** mit PKCE (ohne Secret). Bei einem vertraulichen Client
   das Secret in `OIDC_CLIENT_SECRET` eintragen.
4. Unter „Allowed User Groups“ nur die Gruppe eures Haushalts zulassen – wer
   nicht drin ist, kommt gar nicht erst bis zur App.
5. Client-ID in `OIDC_CLIENT_ID`, `https://id.kanonenwiese.de` in
   `OIDC_ISSUER`.

Wer in der Gruppe `admins` ist (`OIDC_ADMIN_GROUP`), bekommt später die
Admin-Funktionen wie Systemeinstellungen und Backup. Das Profilbild aus Pocket
ID wird beim Login einmal geladen und von Finanzen selbst ausgeliefert.

## Kleine Konfiguration, große Wirkung

| Einstellung | Wofür? |
| --- | --- |
| `PUBLIC_URL` | Öffentliche Adresse, z. B. `https://finanzen.kanonenwiese.de` |
| `POSTGRES_PASSWORD` | Passwort der Datenbank (nur Buchstaben und Ziffern) |
| `SESSION_KEY` | Signiert die Anmeldung; ändern meldet alle ab |
| `SECRETS_KEY` | Verschlüsselt gespeicherte Bank-PINs – **nie ändern, gut aufheben** |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID` | Anmeldung über Pocket ID |
| `FINTS_PRODUCT_ID` | Registrierungsnummer für FinTS (Deutsche Kreditwirtschaft) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | Schlüssel für Push-Nachrichten, einmal erzeugen mit `docker compose run --rm app python -m finanzen vapid` |
| `SMTP_HOST`, `SMTP_FROM`, … | E-Mail-Versand für Benachrichtigungen und Monatsbericht |

Alle Werte mit Erklärung stehen in [.env.example](.env.example). Was dort
schon drinsteht, aber noch nicht genutzt wird, ist entsprechend markiert.

---

## Betriebsecke

### Reverse Proxy (z. B. Nginx Proxy Manager)

Einen Proxy Host `finanzen.kanonenwiese.de` auf `http://garageband:43651`
anlegen, dann:

- **Force SSL** einschalten – ohne HTTPS keine installierbare App und keine
  sichere Anmeldung.
- **HTTP/2** und **HSTS** dürfen an.

Für DNS und Firewall gibt es den n8n-Provisioning-Workflow (Name `finanzen`,
Port `43651`).

### Wichtige Hinweise für den Betrieb

- **Healthcheck:** `https://finanzen.kanonenwiese.de/healthz` – 200 mit
  Version, wenn Datenbank und Datenverzeichnis passen, sonst 503 mit dem
  betroffenen Teil. Gut für Uptime Kuma. `/healthz/live` meldet nur, dass der
  Prozess läuft.
- **Version:** steht unter Einstellungen und in `/healthz`, Schema x.yy.zzz.
- **Updates:** `docker compose pull && docker compose up -d`. Datenbank-Migrationen
  laufen beim Start von selbst, die App im Browser holt sich die neue Version still.
- **`DEV_LOGIN=true`** erlaubt die Anmeldung nur mit einem Namen, ohne Pocket ID –
  **niemals in Produktion**.
- **Backup:** Finanzen schreibt jede Nacht um 3:30 Uhr eine Sicherung aller
  Daten nach `/data/container/finanzen/data/backup/` (`BACKUP_SCHEDULE`,
  `BACKUP_KEEP_DAYS`). Admins sehen sie unter Einstellungen und können dort
  auch sofort sichern. Diesen Ordner zusätzlich auf ein anderes Gerät
  kopieren. Wiederherstellen in eine frische Datenbank (gleiche App-Version):

  ```bash
  docker compose run --rm app python -m finanzen restore /data/backup/finanzen-2026-11-23_0330.json.gz
  ```

- **Image privat?** Ist das Paket auf ghcr.io privat, auf garageband einmal
  `docker login ghcr.io` mit einem Token (Scope `read:packages`) ausführen
  oder das Paket in GitHub auf „public“ stellen.
- **`SECRETS_KEY`** nach dem ersten Speichern einer PIN nie mehr ändern und
  getrennt vom Backup aufbewahren.

## Lizenz

[MIT](LICENSE)

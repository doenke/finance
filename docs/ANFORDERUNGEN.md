# Anforderungen: Haushalts-Finanzstatus

Stand: 22.11.2026 · Status: Entwurf zur Abstimmung

## 1. Ziel

Eine selbst gehostete Web-App (PWA), die das gesamte Vermögen unseres
Haushalts an einem Ort zeigt: Girokonten, Tagesgeld, Depots, Krypto,
Edelmetalle, Immobilien, Altersvorsorge, STAK-Anteile und sonstige Anlagen.
Kredite werden dagegengerechnet. Die App verfolgt, wie sich die Werte
entwickeln, und berechnet die Rendite korrekt, also auch dann, wenn
zwischendurch Geld ein- oder ausgezahlt wird.

Kontostände und Depotbestände sollen möglichst automatisch per FinTS von den
Banken kommen. Wo das nicht geht, per CSV/PDF-Import oder manueller Eingabe.

**Ausbaustufen:** Die erste Version konzentriert sich auf Vermögen und
Rendite. Später soll die App zu einem vollständigen Budget-Planer wachsen
(Kategorien, Cashflow, Budgets, Verträge). Das Datenmodell muss das von
Anfang an ermöglichen (Umsätze vollständig speichern, nicht nur Salden).

## 2. Rahmenbedingungen

| Thema | Festlegung |
| --- | --- |
| Nutzer | Haushalt mit mehreren Personen, Anmeldung je Person |
| Sichtbarkeit | Alle Haushaltsmitglieder sehen alles; Personen dienen der Zuordnung und als Filter |
| Rechte | Admin-Funktionen (Systemeinstellungen, Backup) für Mitglieder der OIDC-Gruppe `admins` |
| Anmeldung | OIDC über Pocket ID („Kanonenwiese SSO“), keine eigenen Passwörter |
| Betrieb | Docker-Container auf garageband, hinter Nginx Proxy Manager (HTTPS) |
| Oberfläche | Deutsch, responsiv, als PWA installierbar, Hell-/Dunkelmodus |
| Basiswährung | EUR |
| Banken/Broker | Sparkasse, DKB, OLB (FinTS); Trade Republic (Import); BSDEX – Bitcoin (Import); Advanzia Kreditkarte (Import/manuell) |

## 3. Begriffe

- **Bankzugang:** Login bei einer Bank (BLZ/URL, Benutzerkennung, ggf. PIN).
  Ein Bankzugang liefert ein oder mehrere Konten/Depots.
- **Konto:** Geldkonto mit Saldo und Umsätzen (Giro, Tagesgeld, Festgeld,
  Kreditkarte, Verrechnungskonto).
- **Depot:** Sammlung von Wertpapierpositionen mit Transaktionen.
- **Anlage:** jeder andere Vermögenswert (Immobilie, Krypto-Wallet, Gold,
  Versicherung, STAK, P2P …) oder jede Verbindlichkeit (Kredit).
- **Bewertung:** Wert einer Anlage zu einem Stichtag (manuell, per Kurs
  oder per Berechnung).
- **Cashflow (extern):** Geld, das in eine Anlage hinein- oder aus ihr
  herausfließt (Einzahlung, Entnahme). Grundlage der Renditeberechnung.
- **TTWROR:** True Time-Weighted Rate of Return, zeitgewichtete Rendite.
  Ignoriert den Zeitpunkt von Cashflows und misst die Güte der Anlage.
- **IRR/IZF:** Internal Rate of Return, interner Zinsfuß,
  geldgewichtete Rendite. Die persönliche Rendite inklusive Timing.

## 4. Funktionale Anforderungen

Priorität: **M** = Muss (MVP), **S** = Soll (Phase 2), **K** = Kann (später).

### 4.1 Haushalt und Personen

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-HH-01 | Benutzer entstehen beim ersten OIDC-Login (Schlüssel `sub`); Name, E-Mail und Avatar werden bei jedem Login aktualisiert. | M |
| F-HH-02 | Jedes Konto, jedes Depot und jede Anlage gehört einer oder mehreren Personen („gemeinsam“) mit Anteilen (Standard 50/50 bei zwei Personen). | M |
| F-HH-03 | Alle Ansichten lassen sich nach Person filtern („alle“, „Person A“, „Person B“, „gemeinsam“). Bei gemeinsamen Anlagen wird der Anteil angerechnet. | M |
| F-HH-04 | Personen ohne eigenen Login (z. B. Kinder) können angelegt werden, um ihnen Anlagen zuzuordnen. | K |

### 4.2 Bankzugänge und FinTS

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-FT-01 | Bankzugänge per FinTS/HBCI anlegen: Bank suchen (BLZ, FinTS-URL aus Bankverzeichnis), Benutzerkennung eintragen, TAN-Verfahren wählen. | M |
| F-FT-02 | Nach dem Anlegen werden die verfügbaren Konten/Depots abgefragt; der Nutzer wählt aus, welche übernommen werden. | M |
| F-FT-03 | **PIN-Speicherung je Bankzugang wählbar:** (a) PIN wird bei jedem Abruf abgefragt und nicht gespeichert, oder (b) PIN wird verschlüsselt gespeichert und automatischer Abruf ist möglich. | M |
| F-FT-04 | Unterstützte TAN-Verfahren: mindestens Decoupled/App-Freigabe (z. B. S-pushTAN der Sparkasse, Freigabe in der DKB-App, App-Freigabe der OLB) sowie chipTAN/photoTAN mit Anzeige der Challenge (Text bzw. Grafik) im Browser. | M |
| F-FT-05 | Abruf von Kontosalden und Umsätzen (CAMT bzw. MT940), inkrementell ab dem letzten Abruf, mit Dublettenerkennung. | M |
| F-FT-06 | Abruf von Depotbeständen (HKWPD): Stückzahl, ISIN, Kurs, Wert, Einstand soweit von der Bank geliefert. | M |
| F-FT-07 | Abruf von Depotumsätzen, sofern die Bank es unterstützt; sonst werden Käufe/Verkäufe aus Bestandsänderungen und Verrechnungskonto-Umsätzen vorgeschlagen und vom Nutzer bestätigt. | S |
| F-FT-08 | Manueller Abruf per Knopf „Jetzt aktualisieren“ (einzeln oder alle Zugänge nacheinander, TAN-Dialog je Bank). | M |
| F-FT-09 | Automatischer Abruf (z. B. täglich nachts) für Zugänge mit gespeicherter PIN. Fordert die Bank eine TAN (z. B. 90-Tage-SCA), wird der Abruf ausgesetzt und der Nutzer benachrichtigt. | S |
| F-FT-10 | Status je Bankzugang sichtbar: letzter erfolgreicher Abruf, letzte Fehlermeldung, nächste fällige SCA-Freigabe soweit bekannt. | M |
| F-FT-11 | Die App nutzt eine eigene, bei der Deutschen Kreditwirtschaft registrierte FinTS-Produkt-ID (konfigurierbar per Env). | M |

### 4.3 Import und manuelle Erfassung

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-IM-01 | CSV-Import für Kontoumsätze mit Spaltenzuordnung; Zuordnungen als Profil speichern (je Bank). | M |
| F-IM-02 | Import von Depot- und Kontotransaktionen für **Trade Republic** (CSV-Export bzw. PDF-Abrechnungen: Kauf, Verkauf, Sparplan, Saveback/Roundup, Dividende, Zinsen, Steuern, Gebühren). Das Verrechnungskonto wird als Konto mitgeführt. | M |
| F-IM-02a | **Advanzia-Kreditkarte:** Import der Monatsabrechnung (PDF bzw. CSV, falls im Kundenportal verfügbar) mit Umsätzen und Saldo; alternativ manuelle Saldo-Erfassung. Der offene Saldo fließt als Verbindlichkeit ins Nettovermögen. | M |
| F-IM-02b | **BSDEX (Börse Stuttgart Digital Exchange):** Import der Transaktionshistorie (CSV-Export) mit Kauf, Verkauf, EUR-Ein- und -Auszahlung, Krypto-Ein- und -Auslieferung und Gebühren. Der Bitcoin-Bestand wird als Krypto-Depot geführt, das EUR-Guthaben bei BSDEX als Verrechnungskonto. Bestand nach Import mit dem tatsächlichen Bestand abgleichbar (Korrekturbuchung bei Abweichung). | M |
| F-IM-03 | Import historischer Depottransaktionen aus **Portfolio Performance** (CSV-Export), um Renditen ab dem echten Kaufdatum zu berechnen. | M |
| F-IM-04 | Import historischer Kontoumsätze (CSV) der übrigen Banken für den Zeitraum vor dem ersten FinTS-Abruf. | M |
| F-IM-05 | Jeder Import zeigt eine Vorschau (neu / Dublette / Fehler) und lässt sich als Ganzes rückgängig machen. | M |
| F-IM-06 | Manuelle Erfassung und Bearbeitung von Konten, Salden, Umsätzen und Depottransaktionen für alles ohne Schnittstelle. | M |
| F-IM-07 | PDF-Import weiterer Abrechnungen (z. B. Sparkasse/Comdirect), falls FinTS-Depotumsätze fehlen. | K |

### 4.4 Wertpapiere und Kurse

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-WP-01 | Wertpapierstamm mit ISIN, WKN, Name, Typ (Aktie, ETF, Fonds, Anleihe, Zertifikat), Währung, Kursquelle. | M |
| F-WP-02 | Täglicher automatischer Kursabruf (Schlusskurs) für alle gehaltenen Wertpapiere. Erste Kursquelle ist **Yahoo Finance**. Kursquellen sind als Adapter umgesetzt, damit später weitere Anbieter hinzukommen. | M |
| F-WP-02a | Zuordnung ISIN → Symbol der Kursquelle (z. B. Yahoo-Ticker `EUNL.DE`): Vorschlag per Suche, manuell korrigierbar, je Wertpapier gespeichert. | M |
| F-WP-02b | **Mehrere Kursquellen verwalten:** Anbieter in den Einstellungen anlegen (ggf. mit API-Key), je Wertpapier eine bevorzugte Quelle plus Ausweichreihenfolge; schlägt eine Quelle fehl, wird die nächste versucht. Herkunft jedes Kurses wird gespeichert. | S |
| F-WP-02c | Fehlende oder veraltete Kurse (älter als X Handelstage) werden in der Oberfläche markiert. | M |
| F-WP-03 | Historische Kurse werden beim Anlegen eines Wertpapiers bzw. nach einem Import rückwirkend geladen, damit Verlaufscharts und Renditen ab Kauf stimmen. | M |
| F-WP-04 | Manuelle Kurseingabe als Fallback und für Werte ohne Kursquelle. | M |
| F-WP-05 | Kapitalmaßnahmen: Splits und Ausschüttungen in Stücken lassen sich erfassen. | S |
| F-WP-06 | Depottransaktionstypen: Kauf, Verkauf, Einlieferung, Auslieferung, Dividende/Ausschüttung, Zinsen, Steuer, Steuererstattung, Gebühr, Vorabpauschale. | M |

### 4.5 Weitere Anlageformen

Alle Anlagen haben einen gemeinsamen Kern (Name, Personen-Zuordnung,
Anlageklasse, Währung, Notizen, Bewertungshistorie, Cashflows) und
typabhängige Zusatzfelder.

| ID | Anlagetyp | Anforderung | Prio |
| --- | --- | --- | --- |
| F-AN-01 | **STAK-Anteile** | Anzahl Zertifikate, Wert je Zertifikat pro Periode (manuell, z. B. jährlich/halbjährlich festgelegt). Käufe/Verkäufe mit Datum, Stückzahl und Preis. **Dividenden** als Transaktion (Betrag je Zertifikat oder gesamt, Datum), einbehaltene Steuern (z. B. niederländische Dividendensteuer) als separate Steuer-Transaktion. Wert zwischen zwei Festsetzungen = letzter festgesetzter Wert. Renditeberechnung wie bei einem Depot. | M |
| F-AN-02 | **Immobilie** | Kaufpreis, Kaufnebenkosten, Kaufdatum, Schätzwerte zu Stichtagen (manuell). Optional Mieteinnahmen als Cashflow. Selbstgenutzt/vermietet. | M |
| F-AN-03 | **Kredit/Darlehen** | Darlehensbetrag, Auszahlungsdatum, Sollzins, anfängliche Tilgung bzw. feste Rate, Zinsbindung bis, Zahlungsrhythmus (monatlich, vierteljährlich), erste Rate. Restschuld wird nach Tilgungsplan berechnet und kann mit Stand aus Kontoauszug/FinTS überschrieben werden (Abweichungen werden angezeigt). Verknüpfbar mit einer Immobilie und mit dem Konto, von dem die Rate abgeht. Fließt negativ ins Nettovermögen. | M |
| F-AN-03a | **Sondertilgungen** | Erfassung ausgeführter Sondertilgungen (Datum, Betrag) und geplanter Sondertilgungen (einmalig oder wiederkehrend, z. B. jährlich 5.000 € im Dezember). Vertragliches Sondertilgungsrecht hinterlegbar (z. B. 5 % des Darlehensbetrags pro Kalenderjahr); die App zeigt, wie viel im laufenden Jahr noch möglich ist, und warnt bei Überschreitung. Sondertilgungen senken die Restschuld sofort und fließen in den Tilgungsplan ein. | M |
| F-AN-03b | **Tilgungsplan** | Berechnung des vollständigen Tilgungsplans je Rate: Datum, Rate, Zinsanteil, Tilgungsanteil, Sondertilgung, Restschuld. Annuitätendarlehen und Darlehen mit fester Tilgung; tilgungsfreie Anlaufzeit möglich. Zusammenfassung: Restschuld am Ende der Zinsbindung, voraussichtliches Laufzeitende, Summe gezahlter und noch zu zahlender Zinsen. Ansicht als Tabelle (nach Jahren gruppiert, aufklappbar) und Chart (Restschuld, Zins-/Tilgungsanteil). Export als CSV. | M |
| F-AN-03c | **Szenarien** | Vergleich des Tilgungsplans mit und ohne geplante Sondertilgungen sowie mit geänderter Rate (Ratenwechsel) bzw. angenommenem Anschlusszins nach der Zinsbindung: Zinsersparnis, Laufzeitverkürzung, Restschuld zum Zinsbindungsende. | S |
| F-AN-04 | **Krypto** | Wird wie ein Depot geführt (z. B. „BSDEX“ oder „Hardware-Wallet“): Transaktionen je Coin (manuell oder per Import), Einstand nach FIFO, automatischer Kursabruf in EUR (Yahoo, z. B. `BTC-EUR`), Rendite wie bei Wertpapieren. Bruchteile mit bis zu 8 Nachkommastellen (Satoshi). Transfers zwischen Börse und eigener Wallet sind Umbuchungen, keine Käufe/Verkäufe. | M |
| F-AN-04a | **Haltefrist Krypto** | Anzeige je Kaufposten, ab wann die einjährige Haltefrist (§ 23 EStG) abgelaufen ist, und wie viel des Bestands bereits steuerfrei verkauft werden könnte. | K |
| F-AN-05 | **Edelmetalle** | Gold/Silber in Gramm oder Unzen mit Feingehalt, Wert per Spotkurs in EUR. | M |
| F-AN-06 | **Altersvorsorge & Versicherungen** | Riester, Rürup, bAV, Renten-/Lebensversicherung, Bausparvertrag: Beiträge als Cashflow, Wert zu Stichtagen aus der jährlichen Standmitteilung (manuell). Optional prognostizierte Rente als Info-Feld. | M |
| F-AN-07 | **Festgeld** | Betrag, Zinssatz, Laufzeit; Wert wird bis Fälligkeit aufgezinst. Benachrichtigung vor Fälligkeit. | M |
| F-AN-08 | **Sonstige Anlage** | Frei definierbar (P2P, Privatdarlehen, Sammlerstücke, Firmenbeteiligung …) mit manuellen Bewertungen und Cashflows. | M |

### 4.6 Bewertung und Rendite

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-RE-01 | Für jedes Konto, jedes Depot, jede Position und jede Anlage gibt es eine tägliche Wertzeitreihe (aus Salden, Bestand × Kurs, Bewertungen, Zinsformel). Zwischen manuellen Bewertungen wird der letzte Wert fortgeschrieben. | M |
| F-RE-02 | **Einfache Kennzahlen:** Einstand, aktueller Wert, Gewinn/Verlust absolut und in Prozent (realisiert und unrealisiert). Einstand nach FIFO. | M |
| F-RE-03 | **TTWROR** für frei wählbare Zeiträume, gesamt und annualisiert. | M |
| F-RE-04 | **IRR/IZF** für frei wählbare Zeiträume, annualisiert. | M |
| F-RE-05 | Standardzeiträume: Heute, 1 M, YTD, 1 J, 3 J, 5 J, seit Beginn, frei. | M |
| F-RE-06 | Kennzahlen lassen sich aggregieren: je Position, Depot, Anlageklasse, Person, Gesamthaushalt. Umbuchungen innerhalb des Haushalts (z. B. Girokonto → Depot-Verrechnungskonto) zählen auf Gesamtebene nicht als Cashflow. | M |
| F-RE-07 | Fremdwährungsbestände werden mit dem Tageskurs (EZB-Referenzkurse) in EUR umgerechnet; die Rendite wird in EUR berechnet. | S |
| F-RE-08 | Die Rechenmethoden werden in der App kurz erklärt (Info-Symbol), damit klar ist, warum sich TTWROR und IZF unterscheiden. | M |

### 4.7 Ansichten

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-UI-01 | **Dashboard Nettovermögen:** Gesamtvermögen, Schulden, Nettovermögen; Veränderung zum Vormonat/Vorjahr; Verlaufschart mit wählbarem Zeitraum; Aufteilung nach Anlageklasse und nach Person. | M |
| F-UI-02 | **Kontenübersicht:** alle Konten, Depots und Anlagen gruppiert nach Typ, mit aktuellem Wert, Veränderung und Datum der letzten Aktualisierung. | M |
| F-UI-03 | **Kontodetail:** Saldoverlauf, Umsatzliste mit Suche und Filter. | M |
| F-UI-04 | **Depotdetail:** Positionen mit Stück, Einstand, Kurs, Wert, G/V, Anteil am Depot; Kennzahlen je Zeitraum (F-RE-05); Wertchart; Transaktionsliste. | M |
| F-UI-05 | **Positionsdetail:** Kurschart mit markierten Käufen/Verkäufen, Kennzahlen, Transaktionen. | M |
| F-UI-06 | **Benchmark-Vergleich:** Performance (TTWROR) eines Depots oder des Gesamtvermögens gegen einen oder mehrere Benchmarks (z. B. MSCI World über einen ETF wie IE00B4L5Y983), indexiert auf 100 zum Beginn des Zeitraums. Benchmark frei wählbar aus allen Wertpapieren mit Kursquelle. | M |
| F-UI-07 | **Anlagedetail** für alle übrigen Anlagetypen mit Bewertungshistorie, Cashflows und Kennzahlen. | M |
| F-UI-08 | Status der Bankzugänge und Aktualisierungs-Knopf von überall erreichbar. | M |
| F-UI-09 | Beträge lassen sich per Knopf verbergen (Privatmodus, z. B. beim Zeigen am Handy). | S |
| F-UI-10 | Asset Allocation mit Soll-Aufteilung und Rebalancing-Hinweis. | K |

### 4.8 Benachrichtigungen

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-NO-01 | Kanäle: **Web-Push** (installierte PWA) und **E-Mail** (SMTP); je Person und Ereignis einstellbar. | S |
| F-NO-02 | Ereignisse: Bankabruf fehlgeschlagen; TAN-/SCA-Freigabe nötig; Festgeld/Zinsbindung läuft in X Tagen aus; Wertveränderung über Schwelle (Tag/Woche, in % oder EUR); Erinnerung an fällige manuelle Bewertung (z. B. STAK-Kurs, Standmitteilung, Immobilienwert jährlich). | S |
| F-NO-03 | **Monatsbericht** per E-Mail: Nettovermögen, Veränderung, Rendite im Monat und YTD, größte Bewegungen. | S |

### 4.9 Export und Backup

| ID | Anforderung | Prio |
| --- | --- | --- |
| F-EX-01 | Export aller Daten als JSON (vollständig, wieder importierbar) sowie Umsätze/Transaktionen/Bewertungen als CSV. | M |
| F-EX-02 | Automatisches tägliches Datenbank-Backup ins Datenverzeichnis mit konfigurierbarer Aufbewahrung; Wiederherstellung dokumentiert. | M |
| F-EX-03 | Gespeicherte PINs sind im Backup nur verschlüsselt enthalten; ohne den Schlüssel aus der Env sind sie wertlos. | M |

### 4.10 Ausblick Budget-Planer (Phase 3, nicht Teil des MVP)

Damit diese Stufe ohne Umbau möglich ist, gilt schon für das MVP:
Umsätze werden vollständig gespeichert (Verwendungszweck, Gegenkonto,
Buchungs-/Valutadatum, Rohdaten) und haben ein (zunächst leeres)
Kategoriefeld.

Geplant sind später:

- Kategorien (hierarchisch) und Regeln zur automatischen Kategorisierung
- Erkennung interner Umbuchungen
- Auswertung Einnahmen/Ausgaben, Sparquote, Cashflow je Monat
- Budgets je Kategorie mit Soll/Ist
- Erkennung von Verträgen und Abos (wiederkehrende Zahlungen) – **umgesetzt**,
  siehe Entscheidungen

## 5. Nicht-funktionale Anforderungen

### 5.1 Sicherheit und Datenschutz

| ID | Anforderung |
| --- | --- |
| N-SI-01 | Anmeldung ausschließlich per OIDC (Authorization Code + PKCE, `state`, `nonce`); Session als signiertes Cookie (`HttpOnly`, `Secure`, `SameSite=Lax`). |
| N-SI-02 | Gespeicherte Bank-PINs werden mit einem Schlüssel aus der Env verschlüsselt (authentifizierte Verschlüsselung, z. B. AES-256-GCM). Klartext-PINs erscheinen nie in Logs, Fehlermeldungen, Exporten oder API-Antworten. |
| N-SI-03 | Nicht gespeicherte PINs leben nur für die Dauer eines FinTS-Dialogs im Speicher. |
| N-SI-04 | Kein Datenverkehr zu Dritten außer zu den Banken und den konfigurierten Kursquellen; Kursabfragen enthalten nur ISIN/Symbol, keine Bestände. Keine CDNs, keine externen Webfonts. |
| N-SI-05 | Alle schreibenden Aktionen werden mit Benutzer und Zeitpunkt protokolliert (Änderungshistorie). |
| N-SI-06 | Seite nicht indexierbar (`noindex`, `robots.txt`). |

### 5.2 Betrieb (Konventionen Kanonenwiese)

| ID | Anforderung |
| --- | --- |
| N-BT-01 | Ein Docker-Image (Server + Frontend) unter `ghcr.io/doenke/finanzen`, Multi-Arch (amd64/arm64), nicht als root. |
| N-BT-02 | PostgreSQL als eigener Dienst im Compose-Stack, ohne Port-Freigabe. Mounts unter `/data/container/finanzen/...`. |
| N-BT-03 | Healthcheck `GET /healthz` (prüft DB und Datenverzeichnis, liefert Version), im Dockerfile und im Compose-Beispiel. |
| N-BT-04 | Konfiguration nur über Env (`.env.example` mit Kommentaren): `PUBLIC_URL`, `PORT`, `TZ`, OIDC-Werte, `SESSION_KEY`, `SECRETS_KEY` (PIN-Verschlüsselung), `FINTS_PRODUCT_ID`, SMTP, VAPID-Schlüssel, Kursquellen-API-Keys. |
| N-BT-05 | Unkonventioneller Port aus 30000–49151, innen und außen gleich. |
| N-BT-06 | Versionierung x.yy.zzz (`versions.json`, `scripts/version.mjs`), sichtbar in der App und im Healthcheck. CI baut, testet, macht einen Smoke-Test und pusht das Image. |
| N-BT-07 | Hintergrundjobs (Kursabruf, automatischer Bankabruf, Backup, Benachrichtigungen) laufen im Container mit eingebautem Scheduler; Zeiten konfigurierbar. |

### 5.3 Oberfläche und Qualität

| ID | Anforderung |
| --- | --- |
| N-UI-01 | Voll nutzbar auf dem Smartphone (ab 360 px Breite) und am Desktop; PWA mit Manifest und Service Worker (Netz zuerst, API nie cachen). |
| N-UI-02 | Hell-/Dunkelmodus nach Systemeinstellung, manuell umschaltbar. |
| N-UI-03 | Deutsche Zahlen- und Datumsformate (1.234,56 €, 22.11.2026). |
| N-UI-04 | Dashboard lädt bei 10 Jahren Historie und ca. 100 Positionen in unter 2 Sekunden (Wertzeitreihen werden vorberechnet und bei Änderungen neu berechnet). |
| N-QA-01 | Renditeberechnungen (TTWROR, IZF, FIFO) sind mit Unit-Tests gegen Referenzwerte abgesichert (z. B. Vergleich mit Portfolio Performance). |
| N-QA-02 | Beträge werden als Dezimalzahlen gespeichert und berechnet, nie als Gleitkommazahlen. |
| N-QA-03 | UI-Texte Deutsch; Code, Bezeichner und Kommentare Englisch. README im bekannten Stil. |

## 6. Vorgeschlagene Architektur

| Baustein | Vorschlag | Begründung |
| --- | --- | --- |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic | `python-fints` ist die ausgereifteste freie FinTS-Bibliothek (Depot, Decoupled-TAN, CAMT). Python bringt außerdem gute Werkzeuge für Zahlen (Decimal, pandas für Zeitreihen, `scipy` für IZF). |
| Datenbank | PostgreSQL 17 | robust für Zeitreihen und Transaktionen, einfache Backups mit `pg_dump` |
| Jobs | APScheduler im selben Prozess | kein zusätzlicher Dienst nötig |
| Frontend | SvelteKit (statisch gebaut, vom Backend ausgeliefert) + Charts (z. B. Apache ECharts, lokal gebündelt) | leicht, schnell auf dem Handy, bereits in anderen Apps genutzt |
| Kursdaten | Adapter-Schnittstelle; Start mit Yahoo Finance (Aktien, ETFs, Fonds, Indizes, Edelmetalle, Krypto), EZB für Wechselkurse; weitere Anbieter (z. B. CoinGecko, EODHD) später als Adapter | Yahoo ist kostenlos, aber eine inoffizielle Schnittstelle, die sich ohne Ankündigung ändern kann; darum austauschbar und mit Fallback |
| Benachrichtigung | Web-Push (VAPID) und SMTP | keine Drittdienste |

Grobes Datenmodell:

```
Person ─┬─< Ownership >─┬─ Account (Konto)        ─< Transaction (Umsatz)
        │               ├─ Portfolio (Depot)      ─< PortfolioTransaction >─ Security ─< Price
        │               └─ Asset (Anlage, typisiert) ─< Valuation, ─< Cashflow
BankLogin ─< Account / Portfolio            (FinTS-Zugang, PIN optional verschlüsselt)
DailyValue (vorberechnete Wertzeitreihe je Account/Portfolio/Position/Asset)
ImportBatch (Herkunft und Rückgängig-Funktion für Importe)
```

## 7. Ausbaustufen

| Phase | Inhalt |
| --- | --- |
| **1 – MVP** | Login/Haushalt, manuelle Konten & Anlagen aller Typen, CSV- und Portfolio-Performance-Import, Trade-Republic- und Advanzia-Import, Kursabruf (Yahoo), Rendite (G/V, TTWROR, IZF), Dashboard, Depotdetail, Benchmark, Export/Backup, PWA |
| **1b – FinTS** | Bankzugänge, manueller Abruf mit TAN-Dialog, Salden, Umsätze, Depotbestände |
| **2** | Automatischer Abruf mit gespeicherter PIN, mehrere Kursquellen mit Fallback, Depotumsätze/Abgleich, Benachrichtigungen, Monatsbericht, Fremdwährungen, Privatmodus |
| **3** | Budget-Planer (siehe 4.10) |

FinTS ist bewusst als eigene Stufe 1b geführt: Es ist der riskanteste Teil
(bankspezifische Eigenheiten, TAN-Verfahren, Produktregistrierung), und
die App ist auch ohne FinTS schon nützlich.

## 8. Entscheidungen

| Thema | Entscheidung |
| --- | --- |
| Banken | Sparkasse, DKB, OLB per FinTS; Trade Republic, BSDEX und Advanzia per Import |
| Kursquelle | Start mit Yahoo Finance, Architektur für mehrere Anbieter |
| STAK | Fester Wert je Periode, Dividenden als Transaktion |
| Steuern | Werden als Transaktion erfasst; keine Auswertung von Verlusttöpfen, Freistellungsaufträgen oder Vorabpauschale |
| Dividenden/Kosten | Werden als Transaktion erfasst; keine eigene Auswertungsansicht im MVP |
| Name | `finanzen`, Subdomain `finanzen.kanonenwiese.de`, Port 43651 |
| Backup | Tägliche JSON-Sicherung aller Tabellen durch die App selbst (statt `pg_dump`, dessen Version im Image nicht zur Datenbank passen würde); Wiederherstellung per `python -m finanzen restore` |
| Rendite | TTWROR mit Zahlungsströmen am Tagesende (Käufe zum Schlusskurs), IZF per XIRR; Kredite zählen nur zum Nettovermögen, nicht zur Rendite |
| Wechselkurse | EZB-Referenzkurse bereits im MVP (F-RE-07 vorgezogen) |
| Kredit-Szenarien | F-AN-03c umgesetzt: bis zu vier Szenarien je Kredit (geplante/zusätzliche Sondertilgungen, Ratenwechsel ab Stichtag, Anschlusszins), Vergleich gegen den Plan ohne Sondertilgungen; Szenarien werden am Kredit gespeichert |
| Kursquellen | onvista (inoffizielle API, ohne Schlüssel, Suche per ISIN, Euro-Handelsplatz bevorzugt) ist Standard; Yahoo bleibt wählbar. Schlägt Yahoo fehl, lädt onvista automatisch über die ISIN nach (F-WP-02b teilweise umgesetzt). Anlass: Yahoo blockierte mit „zu vielen Anfragen“ |
| Ratenänderungen | Kredite haben eine Liste von Ratenänderungen (Datum, neue Rate), auch rückwirkend; gilt für Tilgungsplan, Restschuld, Verlauf und Szenarien |
| Teilen-Ziel | Die installierte PWA nimmt CSV-Dateien über das Teilen-Menü an (Web Share Target, Android/Chromium); die Importseite erkennt Bank-CSV, Portfolio Performance und BSDEX am Kopf der Datei. iOS unterstützt das nicht |
| BSDEX-Import | F-IM-02b umgesetzt anhand eines echten Exports: Werte werden an der Einheit erkannt (Spaltennamen im Export sind verschoben), nur ausgeführte Orders, Gebühr auf den Einstand, Euro-Seite aufs Verrechnungskonto (wird bei Bedarf angelegt). Krypto-Ein-/Auszahlungen sind im Beispiel nicht enthalten und werden als „übersprungen“ gemeldet |
| FinTS | Abruf als Hintergrund-Job mit TAN-Dialog im Browser (Text-TAN, photoTAN-Grafik, Decoupled/App-Freigabe); chipTAN-Flickercode wird nicht dargestellt. Erstabruf 90 Tage Umsätze. Depot: Anfangsbestand laut Bank, später Abweichungen mit Ein-/Auslieferung abgleichen |
| MCP-Server | Eingebauter MCP-Server unter `/mcp` (Streamable HTTP, JSON-Antworten). Anmeldung per OAuth 2.1 mit eigener Autorisierung in der App (Discovery, dynamische Client-Registrierung, PKCE S256, Zustimmungsseite nach Pocket-ID-Login, rotierende Refresh-Tokens, nur Hashes gespeichert). Werkzeuge lesen Konten, Vermögen, Rendite und die Wertpapier-Buchungen eines Depots (`list_trades`) und legen Konten, Stände, Salden, Buchungen und Wertpapier-Transaktionen an; Löschen ist bewusst nicht möglich. Verbundene Assistenten lassen sich in den Einstellungen trennen |
| Bank und Zugang | Bank (Name, BLZ, FinTS-Adresse) ist gemeinsam für den Haushalt; Zugangsdaten (Anmeldename, Kunden-ID, PIN, TAN-Verfahren) gehören einer Person. Nur sie sieht Anmeldename und Kunden-ID und darf mit dem Zugang abrufen, ihn ändern oder Konten verknüpfen; löschen dürfen sie und Admins. Abgerufene Konten sehen weiterhin alle. Bestehende Zugänge wurden bei der Umstellung dem ersten Admin zugeordnet |
| Haltefrist | F-AN-04a umgesetzt für Krypto- und Edelmetall-Konten: Kaufposten nach FIFO, frei ab dem Tag nach dem Jahrestag (§ 23 EStG, 29.02. → 28.02.), steuerfrei verkaufbare Menge, nächste Freigabe, realisierte Gewinne je Jahr getrennt nach innerhalb/außerhalb der Frist, Hinweis auf die Freigrenze (600 € bis 2023, 1.000 € ab 2024). Auch als MCP-Werkzeug |
| Privatmodus | F-UI-09 umgesetzt: verwischt alle Beträge (Money-Komponente, Diagrammachsen, Tooltips), Prozente bleiben; Schalter auf der Übersicht, in der Seitenleiste und in den Einstellungen; gilt je Gerät (localStorage) |
| Benachrichtigungen | F-NO-01 bis -03 umgesetzt. Web-Push ohne Zusatzbibliothek (VAPID ES256, aes128gcm nach RFC 8291), E-Mail per SMTP. Ereignisse je Person: Bankabruf fehlgeschlagen und TAN nötig (nur an den Besitzer des Zugangs), Festgeld/Zinsbindung (X Tage vorher), Nettovermögen ändert sich um X % oder X € (Tag/Woche), Bewertung bzw. manueller Kurs älter als X Monate, Monatsbericht (nur E-Mail). Doppelte Meldungen verhindert ein Protokoll mit Schlüssel und Zeitfenster. E-Mail ist für alle Ereignisse einschließlich Monatsbericht standardmäßig aus (Opt-in je Person) |
| Trade Republic, Advanzia | F-IM-02 und F-IM-02a entfallen als eigene Importer: Die Exporte funktionieren mit dem allgemeinen CSV-Import (F-IM-01) |
| Verträge & Abos | Erster Baustein des Budget-Planers. Kategorien (Ausgabe/Einnahme/Umbuchung, vorbelegt, erweiterbar), `transactions.category_id` mit Fremdschlüssel. Erkennung über Bargeldkonten der letzten 24 Monate: Gruppierung nach normalisiertem Empfänger (bei PayPal & Co. nach Zweck), Intervall wöchentlich bis jährlich mit Toleranz und erlaubter Lücke, bei Mischgruppen erst Trennung nach Verwendungszweck (z. B. Gehalt und Spesen desselben Arbeitgebers), dann nach Betrag; ein einzelner Ausreißer je sechs Abstände (Sonderzahlung) wird toleriert. Vorschläge mit Kategorie per Stichwortregel bzw. eigene IBAN → Umbuchung. Übernommene Regeln ordnen Umsätze laufend zu und setzen deren Kategorie; Hinweise auf Preisänderung und ausbleibende Zahlung. Übersicht: Fixkosten, Einnahmen, Sparraten, frei verfügbar je Monat, Kosten nach Kategorie, Fälligkeiten 30 Tage. Auch als MCP-Werkzeug |
| Rendite je Anlage | Karte auf der Übersicht: je Konto/Anlage (ohne Kredite und Kreditkarten) IZF p. a. (Sortierung, Balken), TTWROR und Gewinn; Zeitraum wählbar, Standard 1 Jahr; folgt dem Personenfilter. Zusammensetzung als Wasserfall: Beitrag = Gewinn der Anlage ÷ durchschnittlich eingesetztes Kapital des Haushalts (Modified Dietz, gleiche Periodenlänge für alle Anlagen), damit sich Beiträge exakt zur einfachen Gesamtrendite addieren; Abweichung zu TTWROR/IZF wird auf der Karte erklärt |
| Gebühren auf Kredite | Buchungen der Art „Gebühr“ am Kredit (z. B. Kosten einer Ratenänderung) erhöhen die Restschuld; eine Gebühr am Tag einer Rate zählt vor dieser Rate (wird also im selben Monat verzinst). Abgeglichen mit einem Bank-Tilgungsplan auf den Cent |
| Verfügbar vs. gebunden | Karte auf der Übersicht (folgt dem Personenfilter): verfügbar = Konten, Tagesgeld, Verrechnung, Depot, Krypto, Edelmetalle inkl. Kreditkarten (negativ); gebunden = Festgeld, Altersvorsorge, Immobilie, STAK, Sonstiges; Kredite separat als Schulden. Je Konto überschreibbar (`details.liquidity`), „frei ab“ aus Festgeld-Fälligkeit, Rentenbeginn oder `details.free_from`. Auch in `get_net_worth` (MCP) |
| Positionen im Vergleich | F-UI-04/05 erweitert: je Depot (und `/wertpapiere` für alle Depots, gleiche Wertpapiere addiert, Personenfilter) Kursverlauf indexiert ab Periodenbeginn (max. 5 Linien, Farben nach stabiler Reihenfolge), Gewichtung, Rendite vs. Schwankung (annualisierte Standardabweichung der Tagesrenditen im letzten Jahr), Kennzahlen 1M/YTD/1J/3J/5J (reine Kursentwicklung), max. Rückgang, Korrelation der Tagesrenditen (divergierend Blau/Rot, grauer Mittelpunkt). Kurshistorie wird mindestens 5 Jahre geladen und fehlende ältere Historie einmalig nachgeholt |
| Umbuchungen | Kategorie-Art `internal` („Umbuchungen“) für Geld zwischen eigenen Konten: zählt weder als Einnahme, Ausgabe noch Sparrate und erscheint nicht unter „Demnächst fällig“. „Sparen & Umbuchungen“ heißt jetzt „Sparen & Anlegen“ (Art `transfer`, zählt als Sparrate). Vorschlag „Umbuchung“ bei eigener IBAN oder dem vollen Namen eines Nutzers als Gegenpartei |
| Monatsbilanz | Seite `/bilanz` (Reiter neben „Verträge“): je Monat aus echten Buchungen Einnahmen, Ausgaben, Gespartes, Sparquote, Übrig. Konten haben eine Rolle (`details.flow_role`: spending/saving; Vorgabe: Giro/Kreditkarte = Alltag, Tagesgeld/Verrechnung/Festgeld/Depots = Sparen). Gespart = Nettofluss Alltag → Sparen (Gegenkonto per IBAN oder gespiegelter Buchung) + Buchungen der Kategorie-Art „transfer“; Bewegungen innerhalb einer Rolle und Kategorie „Umbuchungen“ zählen nicht; Kategorien ohne Zuordnung werden per Stichwortregel geschätzt. Standardmonat ist der letzte vollständige |
| Kategorie-Regeln | Tabelle `category_rules` (Muster als Teilzeichenkette, Feld any/Empfänger/Zweck, Richtung, optional Konto, Kategorie). Reihenfolge: Kategorie aus „Verträge“ > eigene Regel (sort, längeres Muster zuerst) > eingebaute Stichwörter (u. a. neue Kategorien Lebensmittel & Drogerie, Restaurant & Lieferdienst, Einkaufen, Bargeld). Regeln wirken beim Auswerten, nicht gespeichert an der Buchung. Monatsbilanz zeigt die häufigsten Ausgaben ohne Kategorie mit Regel-Editor und Vorschau |
| Haushaltskonten | Kontenrollen heißen Haushaltskonto/Sparkonto und werden im Kontoformular eingestellt; „Verfügbar“ in der Übersicht teilt sich in Haushaltskonten und Angelegt |
| Positionen in „Rendite je Anlage“ | Depots und Krypto (alle Konten mit Positionen) erscheinen dort nicht als Konto, sondern nur mit ihren Positionen (IZF, TTWROR, Gewinn, Beitrag); Kosten/Steuern ohne Position als eigene Zeile „…: Kosten & Steuern“ in der Zusammensetzung. In „Verfügbar und gebunden“ aufklappbar (Stückzahl, aktueller Wert, Gewinn in %) |
| Einzelbuchungen in der Monatsbilanz | Klick auf Kategorie, Einnahme oder Sparroute zeigt die Buchungen des gewählten Monats (Datum, Betrag, Empfänger, Verwendungszweck, Konto); die Auswahl bleibt beim Monatswechsel erhalten |
| Kategorie je Buchung | In den Buchungslisten der Monatsbilanz lässt sich jede Buchung direkt einer Kategorie zuweisen (`PUT /api/transactions/{id}/category`); das schlägt Regeln und Stichwörter, „Automatisch“ setzt zurück. Umbuchungen zwischen eigenen Konten zählen über die Kontenrollen und bekommen keine Auswahl |
| Jahresbilanz | Eigene Seite `/jahresbilanz` (Tab neben Monatsbilanz): Zeiträume „Seit Jahresbeginn“ (bis heute, Vergleich mit denselben Tagen im Vorjahr), „Letzte 12 Monate“ (zwölf abgeschlossene Monate), vergangene Kalenderjahre; Summen, Ø pro Monat, Vorjahresvergleich, Monatstabelle, Kategorien mit Einzelbuchungen. API `GET /api/cashflow/year?period=ytd|12m|JJJJ`. Monatsbilanz ohne Erklärtext oben; `?monat=JJJJ-MM` öffnet einen Monat |
| Alle Buchungen des Monats | Unten in der Monatsbilanz: alle Buchungen der Haushaltskonten im gewählten Monat (neueste zuerst) mit „zählt als“ (Ausgabe, Einnahme, Gespart, Umbuchung), Suche, Filter und Kategorie-Auswahl je Buchung; API liefert sie als `detail.all` nur in der Monatsansicht |
| Altersvorsorge-Projektion | Seite `/vorsorge`, Standard ganzer Haushalt (Rentenbeginn = Mittelwert der Rentenbeginne der Personen – je Person gesetzliche Rente, sonst spätester Vertragsbeginn –, Einkommensteuer je Besitzer), wahlweise je Person: monatliches Einkommen ab Rentenbeginn (Renten + Kapitalentnahme als Annuität) und Kapital bei Rentenbeginn in drei Szenarien (3/5/7 % nominal, einstellbar), alles in heutiger Kaufkraft (Inflation einstellbar, Standard 2 %). Gesetzliche Rente als Vorsorge-Vertrag mit Produkt `gesetzlich` (`expected_pension` = hochgerechnete Rente ohne Anpassungen, gilt als heutige Kaufkraft; `current_pension`, `info_date`, Verlauf in `details.statements`); andere Renten nominal und abgezinst. Sparrate standardmäßig aus der Jahresbilanz (letzte 12 Monate) anteilig zum Kapital der Person – Sparen auf eigene Konten/Depots voll, direkte Beiträge (Kategorie „Sparen & Anlegen“) nur, soweit sie die Beiträge zu Verträgen mit Rentenprognose übersteigen (die stecken schon in deren Prognose, sonst doppelt). Netto grob: KVdR 12,35 % auf gesetzliche, 21,1 % auf Betriebsrente über Freibetrag, ESt Grundtarif 2025 mit Besteuerungs-/Ertragsanteil, Abgeltungsteuer auf Gewinnanteil. Renteninformation per PDF über MCP (`add_pension_statement`), Projektion auch per MCP (`get_retirement_projection`). API `GET /api/retirement` |
| Rentensteigerung | Je Vertrag `details.indexation` (% p. a. ab Rentenbeginn); Standard: gesetzlich wie Inflation (real konstant), Betriebsrente/VBL 1 % (VBLklassik-Dynamisierung), private Verträge 0 %. Die Projektion zeigt zusätzlich Renten und Netto im letzten Entnahmejahr (`pensions_end`, `net_end`, je Rente `monthly_end`) in heutiger Kaufkraft; die Kapitalentnahme ist real konstant |
| FinTS-Umsätze per CAMT | Scheitert der CAMT-Parser von python-fints (z. B. Sparkasse: wiederholte leere Elemente → TypeError), holt `_fetch_transactions` die Rohdaten per `get_transactions_xml` und liest sie mit `services/camt.py` (Buchungs-/Valutadatum, Betrag mit Vorzeichen, Gegenseite, IBAN, Verwendungszweck, Buchungstext; vorgemerkte Umsätze werden übersprungen). Fehler beim Abruf eines Kontos stehen mit Traceback (ohne PIN) im Container-Log |
| Zinsgutschriften | Gutschriften mit „Zinsen für Guthaben“, „Haben-Zins“, „Guthabenzins“, „Zinsgutschrift“, „Zinszahlung“, „Zinsertrag“ oder Buchungstext mit „Zins“ bekommen beim CSV-Import und FinTS-Abruf die Art `interest` (`services/txkind.py`) und zählen damit als Rendite statt als Einzahlung; Migration 0013 stuft vorhandene Buchungen um. Belastungen sind nie Zinsertrag |
| Wert bewerteter Anlagen | Altersvorsorge, Immobilien, Sonstiges: Wert = letzte Bewertung (bzw. Kaufpreis) plus Beiträge/Entnahmen seitdem – überall gleich (Kontoliste, Verfügbar/gebunden, Nettovermögen, Verlauf), damit sich keine Summen widersprechen |
| Navigation und Übersicht | Menü: Übersicht · Konten · Anlagen · Budget (Monats-, Jahresbilanz, Verträge) · Vorsorge · Einstellungen (mit Haushalt, Banken, Protokoll). Übersicht nur „Wo stehen wir?“: Kopf, Verfügbar/gebunden, Verlauf, kompakte Rendite (Gewinn, IZF, TTWROR, je drei beste/schwächste Anlagen). Rendite-Details, Rendite je Anlage und Wertpapiervergleich auf `/anlagen` (`/wertpapiere` leitet um). Keine Aufteilung nach Person oder Anlageklasse mehr auf der Übersicht (Zugewinngemeinschaft: Zuordnung je Person ist für den Haushalt nicht entscheidend; Anlageklassen zeigt die Kontenseite). Rangliste ohne Konten ohne Gewinn/Rendite |
| Kein Personenfilter | Übersicht, Konten und Anlagen zeigen immer den ganzen Haushalt (Zugewinngemeinschaft); die Personenauswahl gibt es nur noch auf der Vorsorge-Seite. Eigentümer-Anteile bleiben an den Konten (Vorsorge, Steuer). Die API-Parameter `person_id` bleiben bestehen |
| Erklärtexte und Zeitraum | Längere Erklärungen stehen hinter einem ⓘ neben der Überschrift (`lib/Info.svelte`) statt als Absatz unter jeder Karte. Ein Zeitraum je Seite: Übersicht (Verlauf steuert auch die Renditekarte), Anlagen (oben rechts für alle Karten); Komponenten haben `period` (bindbar) und `showPeriod` |
| Kaufnebenkosten | Bei Immobilien zählen die Kaufnebenkosten am Kauftag noch zum Wert und gehen erst am Folgetag verloren – so misst die TTWROR den Verlust am ganzen eingesetzten Kapital und nicht am (kleineren) Vortagesvermögen |
| Kategorisieren an einem Ort | Monatsbilanz: Diagramm, Monatsdetail, „Alle Buchungen“ (Kategorie je Zeile, „Regel…“ mit vorgeschlagenem Muster `pattern` aus der API, Knopf „N ohne Kategorie“). Häufig ohne Kategorie (12 Monate), Regeln und Kategorien-Verwaltung auf `/kategorien` (Tab „Kategorien“ im Budget, Link in den Einstellungen) |
| Kontenrollen in der Kontozeile | Haushaltskonten tragen in der Kontenliste ein Etikett; geändert wird die Rolle im Kontoformular („Rolle in der Bilanz“, `details.flow_role`). Die eigene Rollenliste auf der Kontenseite entfällt. Kreditkarten stehen in der Kontenliste bei „Bargeld & Konten“ (wie in Verfügbar/gebunden); Vermögen/Schulden oben zählen wie das Nettovermögen alles unter null als Schulden |
| Einstellungen gegliedert | Abschnitte „Für dich“ (Profil, Benachrichtigungen, Geräte – erst die neuesten vier –, Darstellung), „Haushalt & Daten“ (Haushalt, Kategorien, Banken, Kurse, KI-Assistenten, Export), „Verwaltung“ (Protokoll, Benutzer, Sicherungen) |
| Kleinigkeiten | Cent nur in Buchungslisten und Kontodetails; der laufende Monat ist in der Monatsbilanz blasser und als „läuft“ markiert; Budget-Tabs mit kurzen Namen am Handy |
| Sitzungen | Serverseitig (Tabelle `sessions`, nur Hash des Tokens), Cookie signiert und 30 Tage gültig. Abmelden löscht die Sitzung. Jede Person sieht ihre Geräte und meldet einzelne oder alle anderen ab. Admins können eine Person überall abmelden (Sitzungen und MCP-Tokens) oder sperren (`users.disabled`: keine Anmeldung, keine Tokens). Admin-Rechte werden bei jeder Anmeldung aus der OIDC-Gruppe gelesen; der Zugang zur App wird in Pocket ID über „Allowed User Groups“ geregelt |
| Änderungsprotokoll (N-SI-05) | Tabelle `audit_log`: Zeit, Person, Weg (App oder MCP mit Name des Assistenten), Aktion, Objekt, kurzes Detail. In der App per Middleware für jede schreibende `/api`-Anfrage (ausgenommen Vorschauen, Szenarien, TAN-Antworten, Testnachricht); das Objekt wird vor der Anfrage benannt, damit Gelöschtes seinen Namen behält. Details nur aus einer Feld-Allowlist (Name, Datum, Betrag, Empfänger …), nie Zugangsdaten, PINs oder TANs. MCP-Werkzeuge protokollieren selbst. Dazu An- und Abmeldungen und das Verbinden von Assistenten. Für alle im Haushalt sichtbar (Einstellungen → Änderungsprotokoll) |
| Datenexport | Der JSON-Export für alle lässt `sessions`, `oauth_*` und `push_subscriptions` weg und entfernt bei Bankzugängen PIN und FinTS-Zustand, bei fremden Zugängen zusätzlich Anmeldename, Kunden-ID und TAN-Medium (`scope: export`). Die Admin-Sicherung bleibt vollständig (`scope: backup`) |
| MCP-Zustimmung | Die Zustimmungsseite zeigt den Host der Rücksprungadresse. Nicht in `MCP_TRUSTED_HOSTS` (Standard `claude.ai`, `claude.com`, inkl. Subdomains) und nicht localhost: deutliche Warnung, Erlauben nur mit Bestätigungshäkchen. Registrierung: höchstens 5 Rücksprungadressen à 500 Zeichen, ohne Fragment, Name auf 100 Zeichen gekürzt, höchstens 20 Registrierungen pro Stunde; nie verbundene Clients werden nach einem Tag gelöscht |
| Hauptmenü Bilanz | Der Menüpunkt heißt „Bilanz“ (auch mobil) und führt zur Monatsbilanz; Verträge & Abos und Jahresbilanz sind nur noch Reiter dort (Reihenfolge Monatsbilanz, Jahresbilanz, Verträge & Abos) und markieren den Menüpunkt als aktiv |

## 9. Offene Fragen

1. **FinTS-Produktregistrierung:** Erledigt, Registrierungsnummer liegt vor (wird nur in der `.env` hinterlegt). Am 22.11.2026 beantragt (Kategorie
   „Web-Server“, Produktbezeichnung „finance“). Die Registrierungsnummer
   kommt laut DK meist innerhalb von 10–15 Werktagen und wird dann als
   `FINTS_PRODUCT_ID` eingetragen. Dass die App inzwischen „finanzen“ heißt,
   ändert daran nichts: Die Nummer gilt für die Software, nicht für die
   Subdomain.
2. **Depot-Abdeckung per FinTS:** Bei der Sparkasse ist der Depotabruf per
   FinTS üblich. Bei DKB und OLB ist zu prüfen, ob Depotbestände und
   -umsätze geliefert werden; sonst greift der CSV-Import.
3. **Advanzia und Trade Republic:** Erledigt – die Exporte lassen sich mit dem
   normalen CSV-Import (Spaltenzuordnung) einlesen; eigene Importer sind
   nicht nötig.
4. **Freiwerdende Kreditrate in der Vorsorge (vorgemerkt):** Das Ende des
   Immobilienkredits ist aus dem Tilgungsplan bekannt. Ab dann steht die
   Rate (heute 1.400,30 € im Monat) zusätzlich zum Sparen bereit. Die
   Vorsorge-Projektion soll das berücksichtigen: Sparrate ab Kreditende um
   die Rate erhöhen (abschaltbar, Anteil einstellbar), Restschuld bis dahin
   nicht als Kapital zählen.

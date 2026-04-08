# End-of-Day Trading System

Automatisiertes Analyse- und Simulationssystem für US-Aktien. Das System sammelt tagsüber Kursdaten und Nachrichten, erkennt technische Kauf-/Verkaufssignale und simuliert drei parallele Handelsstrategien (vorsichtig / normal / Risiko). Nach Marktschluss erstellt es automatisch einen PDF-Report mit KI-Analyse.

> **Hinweis:** Dieses System ist ausschließlich für Paper-Trading (Simulation) gedacht. Es führt keine echten Trades aus und stellt keine Anlageberatung dar.

---

## Inhaltsverzeichnis

- [Systemüberblick](#systemüberblick)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [API-Keys einrichten](#api-keys-einrichten)
- [Konfiguration](#konfiguration)
- [Bedienung](#bedienung)
- [Paper-Trading-Modi](#paper-trading-modi)
- [PDF-Report](#pdf-report)
- [Automatisierung mit Cron](#automatisierung-mit-cron)
- [Verzeichnisstruktur](#verzeichnisstruktur)
- [Fehlerbehebung](#fehlerbehebung)

---

## Systemüberblick

```
Vormarkt (08:00)        Intraday (09:00–22:00)        Postmarkt (22:30)
      │                         │                             │
      ▼                         ▼                             ▼
Wirtschafts-         Kursdaten (5-Min-Takt)         EOD-Returns
kalender laden    → Indikatoren berechnen        → KI-Analyse (Claude/GPT)
                  → Signale prüfen              → PDF-Report erstellen
                  → News & Sentiment laden
                  → Paper-Trading simulieren
                    (3 Modi parallel)
```

**Datenquellen (alle kostenlos):**
- **Yahoo Finance** – OHLCV-Kursdaten (Intraday + EOD)
- **Finnhub Free-Tier** – News-Headlines & Sentiment
- **Investing.com** – Wirtschaftskalender
- **Anthropic Claude / OpenAI GPT** – KI-Tagesanalyse

**Technische Indikatoren:** SMA, EMA, RSI, MACD, Bollinger Bänder, Stochastik, OBV, VWAP

---

## Voraussetzungen

- Python **3.11** oder neuer
- Betriebssystem: Linux, macOS oder Windows
- Internetverbindung (für Kursdaten und API-Aufrufe)
- Mindestens einen API-Key (Claude **oder** OpenAI) für die KI-Analyse

---

## Installation

### 1. Repository klonen

```bash
git clone <repository-url>
cd trade
```

### 2. Virtuelle Umgebung erstellen (empfohlen)

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows
```

### 3. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

Das installiert folgende Bibliotheken:

| Paket | Verwendung |
|---|---|
| `yfinance` | Kursdaten von Yahoo Finance |
| `pandas-ta` | Technische Indikatoren |
| `finnhub-python` | News & Sentiment |
| `requests` + `beautifulsoup4` | Wirtschaftskalender |
| `anthropic` | Claude KI-API |
| `openai` | OpenAI GPT-API (optional) |
| `reportlab` | PDF-Erstellung |
| `pyyaml` | Konfigurationsdatei |

---

## API-Keys einrichten

Öffne `config.yaml` und trage deine API-Keys ein:

### Anthropic Claude (empfohlen)

1. Registrierung unter [console.anthropic.com](https://console.anthropic.com)
2. API-Key erstellen unter *Settings → API Keys*
3. In `config.yaml` eintragen:

```yaml
ai_provider: "claude"

claude:
  api_key: "sk-ant-api03-..."    # hier deinen Key eintragen
  model: "claude-sonnet-4-6"
```

### OpenAI GPT (alternativ)

1. Registrierung unter [platform.openai.com](https://platform.openai.com)
2. API-Key erstellen unter *API Keys*
3. In `config.yaml` eintragen:

```yaml
ai_provider: "chatgpt"

openai:
  api_key: "sk-proj-..."         # hier deinen Key eintragen
  model: "gpt-4o"
```

### Finnhub (optional, für News-Sentiment)

1. Kostenlose Registrierung unter [finnhub.io](https://finnhub.io)
2. API-Key aus dem Dashboard kopieren
3. In `config.yaml` eintragen:

```yaml
finnhub:
  api_key: "d1abc2..."           # hier deinen Key eintragen
```

> Ohne Finnhub-Key läuft das System weiterhin – News-Sentiment wird dann übersprungen.

---

## Konfiguration

Alle Einstellungen befinden sich in `config.yaml`. Die wichtigsten Parameter:

### Tickers anpassen

```yaml
tickers:
  - AAPL
  - MSFT
  - NVDA
  - TSLA      # beliebige US-Ticker ergänzen
  - SPY
```

### Signalparameter

```yaml
signal:
  sma_fast: 20           # Periode der schnellen SMA (Golden Cross)
  sma_slow: 50           # Periode der langsamen SMA
  rsi_threshold: 50      # RSI muss UNTER diesem Wert liegen (Kauf-Signal)
  macd_signal: true      # MACD-Histogramm muss positiv sein
  obv_rising: true       # OBV muss steigen
  volume_multiplier: 1.5 # Volumen > 1,5× 20-Tage-Durchschnitt
```

### Paper-Trading Startkapital

```yaml
paper_trading:
  enabled: true
  starting_capital: 10000.0   # Startkapital in USD
  commission_pct: 0.001       # 0,1 % Transaktionskosten
```

### Handelszeitfenster (MEZ)

```yaml
market_hours:
  open: "15:30"               # US-Marktöffnung (New York = MEZ − 6h)
  close: "22:00"              # US-Marktschluss
  intraday_interval_sec: 300  # Abruf-Intervall: 300 = 5 Minuten
```

---

## Bedienung

### Vollständiger Tagesablauf (alle Phasen)

```bash
python run_daily.py
```

Führt alle drei Phasen nacheinander aus:
1. Wirtschaftskalender laden
2. Intraday-Loop bis Marktschluss (blockiert bis 22:00 MEZ)
3. Postmarkt: Returns berechnen, KI-Analyse, PDF erstellen

---

### Einzelne Phasen aufrufen

#### Nur Vormarkt (Wirtschaftskalender)
```bash
python run_daily.py --premarket
```

#### Nur Intraday-Loop
```bash
python run_daily.py --intraday
```
Der Loop läuft bis zur konfigurierten Marktschlusszeit und kann mit **Strg+C** sicher unterbrochen werden (Paper-Trading-Stand wird dabei gesichert).

#### Nur Postmarkt (Report erstellen)
```bash
python run_daily.py --postmarket
```
Nützlich um den Report für einen bereits gelaufenen Tag nachträglich zu erstellen.

---

### Anderen Handelstag verarbeiten

```bash
python run_daily.py --postmarket --date 2026-04-07
```

### Paper-Trading deaktivieren

```bash
python run_daily.py --no-paper-trading
```

### Andere Konfigurationsdatei verwenden

```bash
python run_daily.py --config meine_config.yaml
```

---

### Ausgabe nach Marktschluss

Nach dem Postmarkt erscheint im Terminal:

```
=================================================================
  PAPER-TRADING TAGESERGEBNIS
=================================================================
  CONSERVATIVE   | Portfolio:  10.142,30 | P&L: +142,30 (+1,42%) | Trades:  2 | Positionen: 1
  NORMAL         | Portfolio:   9.987,10 | P&L:  -12,90 (-0,13%) | Trades:  5 | Positionen: 3
  RISK           | Portfolio:  10.843,20 | P&L: +843,20 (+8,43%) | Trades:  8 | Positionen: 4
=================================================================

Report gespeichert: ./daily_reports/2026-04-08.pdf
```

---

## Paper-Trading-Modi

Das System simuliert drei Handelsstrategien **gleichzeitig** mit demselben Startkapital:

| | Vorsichtig | Normal | Risiko |
|---|---|---|---|
| **Positionsgröße** | max. 5 % | max. 10 % | max. 25 % |
| **Max. Positionen** | 3 | 5 | 8 |
| **Stop-Loss** | 2 % | 3 % | 5 % |
| **Take-Profit** | 5 % | 8 % | 15 % |
| **Min. Signalstärke** | 80 % | 60 % | 40 % |

**Wie ein Signal ausgelöst wird:**

Ein Kauf-Signal (BUY) entsteht, wenn **alle Pflichtbedingungen** und mindestens 60 % aller konfigurierten Bedingungen erfüllt sind:

| Bedingung | Pflicht |
|---|---|
| SMA(20) > SMA(50) — Golden Cross | Ja |
| RSI < 50 | Ja |
| MACD-Histogramm > 0 | Optional |
| OBV steigt | Optional |
| Volumen > 1,5× Durchschnitt | Optional |

Ein Verkauf-Signal (SELL) entsteht bei Death Cross (SMA(20) < SMA(50)) oder überkauftem RSI (> 70).

**Kapital und Positionen werden täglich fortgeschrieben.** Am nächsten Tag startet jeder Modus mit dem Endstand des Vortages (Cash + offene Positionen).

Die Modi können in `config.yaml` unter `paper_trading.modes` frei angepasst werden.

---

## PDF-Report

Der tägliche Report wird unter `daily_reports/YYYY-MM-DD.pdf` gespeichert und enthält drei Seiten:

**Seite 1 – Tagesübersicht**
- KPI-Boxen: Signalanzahl, Hit-Rate, Avg. Return, Profit-Factor, Max. Drawdown
- Wirtschaftskalender (HIGH/MEDIUM-Impact Events)
- Signaltabelle farbcodiert (grün = Gewinner, rot = Verlierer)

**Seite 2 – Analyse**
- Vollständige Performance-Kennzahlen inkl. Information Coefficient
- KI-Fazit (3–5 Absätze, natürliche Sprache)
- Bis zu 5 konkrete Verbesserungsvorschläge vom KI-Modell

**Seite 3 – Paper-Trading**
- Vergleichstabelle aller drei Modi nebeneinander
- Offene Positionen je Modus (mit Stop-Loss, Take-Profit, unrealisiertem P&L)
- Trade-Historie des Tages farbcodiert

---

## Automatisierung mit Cron

Für vollautomatischen Betrieb (Linux/macOS) die Crontab bearbeiten:

```bash
crontab -e
```

Folgende Zeilen einfügen (Pfad zum Projektordner anpassen):

```cron
# Vormarkt: Wirtschaftskalender laden (08:00 MEZ, Mo–Fr)
0 8 * * 1-5  cd /pfad/zum/trade && .venv/bin/python run_daily.py --premarket

# Intraday-Loop starten (09:00 MEZ, läuft bis Marktschluss 22:00)
0 9 * * 1-5  cd /pfad/zum/trade && .venv/bin/python run_daily.py --intraday

# Postmarkt: Report erstellen (22:30 MEZ)
30 22 * * 1-5  cd /pfad/zum/trade && .venv/bin/python run_daily.py --postmarket
```

**Windows (Task-Planer):**

Drei geplante Tasks mit diesen Befehlen erstellen:
```
C:\pfad\trade\.venv\Scripts\python.exe run_daily.py --premarket
C:\pfad\trade\.venv\Scripts\python.exe run_daily.py --intraday
C:\pfad\trade\.venv\Scripts\python.exe run_daily.py --postmarket
```

---

## Verzeichnisstruktur

```
trade/
├── config.yaml              # Konfiguration (API-Keys, Parameter)
├── requirements.txt         # Python-Abhängigkeiten
├── run_daily.py             # Hauptskript / Einstiegspunkt
│
├── src/
│   ├── db.py                # SQLite-Schema & Datenbankfunktionen
│   ├── data_fetch.py        # Kursdaten, Indikatoren, News, Kalender
│   ├── signal_logic.py      # Regelbasierte Signalgenerierung
│   ├── ai_verifier.py       # KI-Analyse (Claude / OpenAI)
│   ├── pdf_report.py        # PDF-Erstellung (ReportLab)
│   └── trade_simulator.py   # Paper-Trading-Simulation (3 Modi)
│
├── data/
│   └── trading.db           # SQLite-Datenbank (auto-erstellt)
│
├── daily_reports/
│   └── YYYY-MM-DD.pdf       # Tages-Reports
│
└── logs/
    └── YYYY-MM-DD.log       # Tagesprotokoll
```

**Datenbank-Tabellen:**

| Tabelle | Inhalt |
|---|---|
| `prices` | OHLCV-Kursdaten je Ticker und Zeitstempel |
| `indicators` | Berechnete technische Indikatoren |
| `signals` | Ausgelöste Kauf-/Verkaufssignale mit EOD-Return |
| `events` | Wirtschaftskalender-Ereignisse |
| `news_sentiment` | News-Headlines mit Sentiment-Score |
| `paper_portfolio` | Täglicher Portfolio-Stand je Modus |
| `paper_positions` | Aktuelle offene Positionen je Modus |
| `paper_trades` | Vollständige Trade-Historie je Modus |

---

## Fehlerbehebung

**`ModuleNotFoundError`**
```bash
pip install -r requirements.txt
```

**`pandas_ta` Fehler bei der Installation**
```bash
pip install pandas-ta --pre
# oder alternativ:
pip install pandas-ta==0.3.14b
```

**Yahoo Finance liefert keine Daten**

Yahoo Finance kann gelegentlich Rate-Limits setzen. Das System versucht bis zu 3× automatisch. Alternativ den `period`-Wert in `config.yaml` anpassen:
```yaml
yfinance:
  period: "5d"   # auf "1d" reduzieren bei Problemen
```

**KI-API antwortet nicht**

API-Key in `config.yaml` prüfen. Fehlermeldungen finden sich in `logs/YYYY-MM-DD.log`. Das PDF wird auch ohne KI-Analyse erstellt (mit Hinweistext statt Analyse).

**Wirtschaftskalender leer**

Investing.com kann Scraping blockieren. Das System ignoriert diesen Fehler und läuft weiter. Events-Spalte im PDF bleibt dann leer.

**Paper-Trading startet bei 0 statt Vortagesstand**

Der Stand des Vortages wird aus der Datenbank geladen. Sicherstellen dass `data/trading.db` nicht gelöscht wurde. Mit diesem Befehl lässt sich der aktuelle Stand prüfen:
```bash
sqlite3 data/trading.db "SELECT mode, trade_date, total_value, total_pnl_pct FROM paper_portfolio ORDER BY trade_date DESC LIMIT 6;"
```

---

## Lizenz

Dieses Projekt dient ausschließlich zu Lern- und Forschungszwecken. Alle verwendeten Daten unterliegen den Nutzungsbedingungen der jeweiligen Datenanbieter (Yahoo Finance, Finnhub, Investing.com). Kein Teil dieses Systems stellt eine Anlageberatung oder Handelsempfehlung dar.

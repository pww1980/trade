<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Konzept für ein End‑of‑Day‑Trading‑System mit kostenlosen APIs und wählbarer KI (ChatGPT / Claude)

## 1. Überblick

Das System sammelt während des Handelstages Kursdaten, technische Indikatoren und relevantes Nachrichten‑Sentiment, speichert alles in einer lokalen Datenbank und erzeugt nach Handelsschluss ein PDF‑Report, das die generierten Kauf‑/Verkaufssignale sowie eine KI‑basierte Verifizierung enthält [^1][^2][^3].
Es wird kein Dashboard benötigt – alle Auswertungen erfolgen über Skripte und das tägliche PDF.

## 2. Architektur‑Komponenten

| Komponente | Aufgabe | Technologie / API (kostenfrei) | Hinweis |
| :-- | :-- | :-- | :-- |
| **Datenbeschaffung** | Kurs‑OHLCV, Basis‑Fundamentals, Wirtschaftskalender, News‑Headlines \& Sentiment | -  **Yahoo Finance** (`yfinance`) – EOD‑ und Intraday‑Kurse (frei) [^4][^5][^6]  <br>-  **Finnhub Free‑Tier** – News‑Headlines und einfaches Sentiment (verzögert ~30 s) [^7]  <br>-  **Investing.com Economic Calendar** (free CSV/JSON) – geplante hoch‑impact‑Events [^8]  <br>-  **Alpha Vantage Free‑Tier** – alternativ für Intraday‑Kurse (Rate‑Limit beachten) [^2] | Alle Endpunkte sind ohne Kosten nutzbar; für produktive Nutzung kann bei Bedarf auf kostenpflichtige Pläne gewechselt werden. |
| **Technische Indikator‑Berechnung** | SMA/EMA, MACD, RSI, Stochastik, Bollinger‑Bänder, OBV, VWAP usw. | **pandas‑ta** oder **ta‑lib** (Open‑Source Python‑Bibliotheken) [^4][^5][^6][^9][^10][^11][^12][^13] | Keine externe API nötig – reine Berechnung auf den gespeicherten Kursen. |
| **Signalgenerierung** | Regelbasierte Kauf‑/Verkaufssignale (z. B. Golden Cross + RSI < 50 + steigendes OBV) + Volumen‑Bestätigung | Eigene Logik in Python, nutzt die berechneten Indikatoren [^14][^15][^16][^17] | Schwellenwerte können über eine Konfigurationsdatei angepasst werden. |
| **Datenbank** | Speicherung von Rohkursen, Indikatoren, Signalen, Ereignissen und News‑Sentiment pro Ticker und Timestamp | **SQLite** (einzel‑Datei,零配置) – Tabellen: `prices`, `indicators`, `signals`, `events`, `news_sentiment` [^18][^19] | Für Skalierbarkeit kann später auf PostgreSQL gewechselt werden, aber für den Prototyp reicht SQLite aus. |
| **KI‑Verifizierung (End‑of‑Day)** | Nach Handelsende werden die Signale mit den tatsächlich erzielten Returns verglichen; ein LLM bewertet die Qualität und liefert eine kurze natürliche Sprach‑Zusammenfassung | Wahl zwischen **OpenAI GPT‑4o (ChatGPT)** oder **Anthropic Claude 3** über deren REST‑APIs – API‑Key wird in einer Config‑Datei angegeben [^20][^21][^22][^23][^24][^25][^26] | Der Prompt enthält: Signal‑Liste, tägliche Performance‑Metriken (Hit‑Rate, Profit‑Factor, Max‑Drawdown, IC) und bittet das Modell um ein kurzes Fazit sowie Verbesserungsvorschläge. |
| **PDF‑Erstellung** | Zusammenfassung der Signale, Performance‑Kennzahlen und KI‑Fazit in einem lesbaren Bericht | **ReportLab** oder **WeasyPrint** (beide Open‑Source) – erzeugt ein ein‑ oder zweiseitiges PDF [^18][^19] | Keine zusätzlichen kostenpflichtigen Tools nötig. |
| **Konfigurationsdatei** | Zentraler Ort für API‑Keys, gewählte KI, Schwellenwerte für Signale, Pfade zur Datenbank und Ausgabe‑Ordner | **YAML** (`config.json` oder `config.yaml`) – Beispielstruktur unten | Erleichtert den Wechsel zwischen ChatGPT und Claude sowie das Anpassen von Parametern ohne Code‑Änderung. |

## 3. Datenfluss (typischer Tag)

1. **Vor Marktopen**
    - Lade Wirtschafts‑Kalender → speichere Events in Tabelle `events`.
    - Lade aktuelle Watch‑List (z. B. S\&P 500‑Komponenten) aus einer statischen Liste oder einem kostenlosen Screener (Investing.com) [^27].
2. **Während des Handels** (alle 5 Minuten oder per WebSocket bei Verfügbarkeit)
    - Lade Kursdaten für alle Watch‑List‑Tickers via `yfinance` (oder Alpha Vantage) → speichere OHLCV in `prices`.
    - Berechne Indikatoren → schreibe in `indicators`.
    - Prüfe Signalregeln → falls erfüllt, schreibe Eintrag in `signals` (inkl. Signal‑Stärke, Zeitstempel).
    - Ziehe News‑Headlines \& Sentiment von Finnhub → speichere in `news_sentiment` (Ticker, Timestamp, Sentiment‑Score, Headline) [^7].
3. **Nach Handelsende**
    - Berechne tägliche Returns (Close‑to‑Close) für jeden Ticker, der ein Signal hatte.
    - Aggregate Performance‑Kennzahlen: Hit‑Rate, durchschnittlicher Return, Profit‑Factor, Max‑Drawdown, Information Coefficient (IC) [^28][^29][^30][^31][^32][^33].
    - Erstelle Prompt für das gewählte LLM (ChatGPT oder Claude) → sende Anfrage → empfange KI‑Fazit.
    - Generiere PDF mit:
        * Übersicht über getätigte Signale (Ticker, Signal‑Typ, Zeit, Indikator‑Werte)
        * Performance‑Tabelle
        * KI‑Fazit und mögliche Optimierungsvorschläge
    - Speichere PDF im Ausgabeordner (z. B. `daily_reports/YYYY-MM-DD.pdf`).

## 4. Beispiel‑Konfigurationsdatei (`config.yaml`)

```yaml
# Allgemein
data_dir: ./data               # Ort für SQLite‑DB und Logs
output_dir: ./daily_reports    # PDF‑Ausgabe
db_name: trading.db

# Kostenlose APIs
yfinance:
  enabled: true
finnhub:
  api_key: "YOUR_FINNHUB_FREE_KEY"   # kann leer sein, dann nur headlines ohne Sentiment
investing_calendar:
  url: "https://www.investing.com/economic-calendar/"
alpha_vantage:
  api_key: "demo"                     # Free‑Tier Key (Rate‑Limit beachten)

# KI‑Auswahl (ein von beiden aktiv)
ai_provider: "chatgpt"   # alternativ: "claude"
openai:
  api_key: "OPENAI_API_KEY"
  model: "gpt-4o"
claude:
  api_key: "ANTHROPIC_API_KEY"
  model: "claude-3-5-sonnet-20241022"

# Signalparameter (kann per Strategie angepasst werden)
signal:
  sma_fast: 20
  sma_slow: 50
  rsi_threshold: 50
  macd_signal: true
  obv_rising: true
  volume_multiplier: 1.5   # Volumen muss > 1.5 x 20‑Tage‑Durchschnitt sein
```


## 5. Implementierungsschritte (kurzer Überblick)

1. **Umgebung vorbereiten**

```bash
pip install yfinance pandas-ta finnhub-python reportlab pyyaml openai anthropic
```

2. **Datenbank initialisieren** (SQLite‑Schema anlegen).
3. **Modul `data_fetch.py`** – täglicher Ablauf: Kursdownload, Indikatorberechnung, Signalprüfung, News‑Abruf, alles in die DB schreiben.
4. **Modul `signal_logic.py`** – enthält die règle‑basierten Funktionen (`generate_signal(row)`) die aus den Indikatoren ein Signal zurückgeben.
5. **Modul `ai_verifier.py`** – liest die Performance‑Kennzahlen aus der DB, baut den Prompt entsprechend der gewählten KI‑Provider und ruft die API auf.
6. **Modul `pdf_report.py`** – zieht Signale, Metriken und KI‑Fazit aus der DB und erstellt das PDF via ReportLab.
7. **Hauptskript `run_daily.py`** – lädt Config, ruft die Module in der richtigen Reihenfolge auf, schreibt Log‑Ausgabe.
8. **Zeitplanung** – mittels `cron` (Linux) oder Task‑Scheduler (Windows) das Skript täglich nach Handelsende (z. B. 18:30 MEZ) ausführen.

## 6. Erwartete Ergebnisse

- **Transparenz**: Alle Rohdaten, Indikatoren und Signale liegen in der SQLite‑DB nachvollziehbar vor.
- **KI‑Feedback**: Das tägliche PDF enthält neben den harten Zahlen eine natürliche Sprachbewertung durch das ausgewählte LLM, wodurch dem Benutzer sofort erkennbar wird, ob das Signal‑Set gut funktionierte oder wo Justierungen nötig sind.
- **Erweiterbarkeit**: Durch die klare Modularisierung lassen sich später kostenpflichtige Datenquellen (z. B. Polygon.io für Tick‑Data) oder erweiterte KI‑Ansätze (Reinforcement Learning, eigene Sentiment‑Modelle) ohne Umstrukturierung des Kerns einfügen.


## 7. Weiterführende Literatur \& Quellen (Auswahl)

- Technische Indikatoren \& deren Anwendung: [^4][^5][^6][^9][^10][^11][^12][^13]
- Regelbasierte Signale \& Validierung: [^14][^15][^16][^17][^18][^19]
- Kostenlose Finanz‑ \& Nachrichten‑APIs: [^1][^2][^7][^8][^27]
- KI‑gestützte Signalverbesserung \& Sentiment‑Modelle: [^20][^21][^22][^23][^24][^25][^26]
- Performance‑Metriken \& Walk‑Forward‑Analyse: [^28][^29][^30][^31][^32][^33]

---

*Dieses Konzept kann von einer KI (z. B. ChatGPT oder Claude) direkt als Grundlage für die Umsetzung eines funktionierenden End‑of‑Day‑Trading‑Systems genommen werden. Alle genannten APIs besitzen kostenfreie Tier‑Optionen, die für den Prototyp ausreichend sind; bei Bedarf lässt sich jede Komponente leicht auf eine kostenpflichtige Variante hochskalieren.*

<div align="center">⁂</div>

[^1]: https://finlight.me

[^2]: https://newsdata.io/blog/best-stock-news-api/

[^3]: https://www.stockgeist.ai/stock-market-api/

[^4]: https://finanzradar.de/trading/daytrading-lernen/daytrading-indikatoren/

[^5]: https://www.tradingfreaks.com/post/technischen-indikatoren-daytrader

[^6]: https://trading.de/daytrading/daytrading-indikatoren/

[^7]: https://finnhub.io/docs/api/news-sentiment

[^8]: https://www.investing.com/economic-calendar

[^9]: https://www.ig.com/de/trading-strategien/die-10-wichtigsten-technischen-chart-indikatoren-190509

[^10]: https://bitsgap.com/de/blog/seven-best-technical-indicators-for-day-trading-3

[^11]: https://tradersunion.com/de/interesting-articles/day-trading-what-is-day-trading/technical-indicators/

[^12]: https://www.kagels-trading.de/technische-indikatoren-trader/

[^13]: https://trading.de/indikatoren/

[^14]: https://www.ig.com/de/trading-strategien/was-ist-ein-kaufsignal-und-wie-erkennen-sie-es--230524

[^15]: https://tai-pan.de/blog/technische-indikatoren

[^16]: https://www.binance.com/de/academy/articles/5-essential-indicators-used-in-technical-analysis

[^17]: https://www.investopedia.com/top-7-technical-analysis-tools-4773275

[^18]: https://trading-strategies.academy/archives/1875

[^19]: https://github.com/abhy-kumar/project-M1NT/

[^20]: https://www.youtube.com/watch?v=gyE3bYPsvu8

[^21]: https://aisengtech.com/2022/09/27/how-to-build-machine-learning-model-to-generate-trading-signal/

[^22]: https://mbrenndoerfer.com/writing/ml-trading-strategy-signal-generation-sentiment-reinforcement-learning

[^23]: https://www.quantlabsnet.com/post/build-ai-trading-agents-with-python-your-guide-to-market-navigation

[^24]: https://arxiv.org/html/2509.16707v1

[^25]: https://www.ijsat.org/papers/2025/3/7682.pdf

[^26]: https://www.tandfonline.com/doi/full/10.1080/23322039.2025.2490818

[^27]: https://www.investing.com/stock-screener

[^28]: https://ftp.decadental.com/blog/best-end-of-day-trading-strategies-1767646972

[^29]: https://www.oreateai.com/blog/analysis-of-endofday-trading-signals-characteristics-and-strategies-after-major-funds-accumulate/0ccab02698b13c4ecc61f2a1435fdcb7

[^30]: https://www.youtube.com/watch?v=72R0hd3jrYw

[^31]: https://www.youtube.com/watch?v=zxYZ60V-w0M

[^32]: https://www.kavout.com/market-lens/trading-signals-and-technical-indicators-for-effective-market-scanning

[^33]: https://www.xtb.com/en/education/how-to-use-trading-signals-effectively-practical-guide


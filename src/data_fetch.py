"""
data_fetch.py – Kursdaten, Indikatoren, News-Sentiment und Wirtschaftskalender.
"""

import logging
import time
from datetime import datetime, date
from typing import Optional
import sqlite3

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OHLCV via yfinance
# ---------------------------------------------------------------------------

def fetch_ohlcv(ticker: str, interval: str = "5m", period: str = "5d") -> Optional[pd.DataFrame]:
    """Lädt OHLCV-Daten via yfinance. Gibt DataFrame oder None bei Fehler zurück."""
    try:
        import yfinance as yf
        df = yf.download(ticker, interval=interval, period=period, progress=False, auto_adjust=True)
        if df.empty:
            logger.warning("yfinance: Keine Daten für %s", ticker)
            return None
        df.index = pd.to_datetime(df.index)
        # Neuere yfinance-Versionen liefern MultiIndex-Spalten wie ("Close", "AAPL").
        # Auf einfache Spaltennamen reduzieren.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        logger.debug("yfinance: %d Zeilen für %s geladen", len(df), ticker)
        return df
    except Exception as exc:
        logger.error("yfinance-Fehler für %s: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# Technische Indikatoren via pandas-ta
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Berechnet SMA, EMA, RSI, MACD, Bollinger Bänder, Stochastik, OBV, VWAP.
    Gibt erweiterten DataFrame zurück.
    """
    try:
        import pandas_ta as ta
    except ImportError:
        logger.error("pandas-ta nicht installiert. `pip install pandas-ta`")
        return df

    sc = cfg.get("signal", {})
    fast = sc.get("sma_fast", 20)
    slow = sc.get("sma_slow", 50)

    df = df.copy()

    # Spaltennamen normalisieren (yfinance gibt manchmal Großbuchstaben)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    df.ta.sma(length=fast, append=True)
    df.ta.sma(length=slow, append=True)
    df.ta.ema(length=fast, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
    df.ta.obv(append=True)

    # VWAP (benötigt High, Low, Close, Volume)
    try:
        df.ta.vwap(append=True)
    except Exception:
        pass

    # 20-Tage Volumen-Durchschnitt
    if "Volume" in df.columns:
        df["volume_avg20"] = df["Volume"].rolling(20).mean()

    logger.debug("Indikatoren berechnet: %d Spalten", len(df.columns))
    return df


# ---------------------------------------------------------------------------
# News & Sentiment via Finnhub
# ---------------------------------------------------------------------------

def fetch_news_sentiment(ticker: str, api_key: str, from_date: str = None, to_date: str = None) -> list[dict]:
    """
    Lädt News-Headlines und Sentiment-Scores via Finnhub Free-Tier.
    Gibt Liste von Dicts zurück: {ticker, timestamp, headline, sentiment, source}
    """
    if not api_key or api_key == "YOUR_FINNHUB_FREE_KEY":
        logger.debug("Finnhub API-Key nicht gesetzt – überspringe Sentiment für %s", ticker)
        return []

    today = str(date.today())
    from_date = from_date or today
    to_date = to_date or today

    url = "https://finnhub.io/api/v1/company-news"
    params = {"symbol": ticker, "from": from_date, "to": to_date, "token": api_key}

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            articles = resp.json()
            results = []
            for art in articles[:20]:  # max 20 Headlines pro Ticker
                results.append({
                    "ticker": ticker,
                    "timestamp": datetime.fromtimestamp(art.get("datetime", 0)).isoformat(),
                    "headline": art.get("headline", ""),
                    "sentiment": _simple_sentiment(art.get("headline", "")),
                    "source": art.get("source", "finnhub"),
                })
            logger.debug("Finnhub: %d Headlines für %s", len(results), ticker)
            return results
        except requests.RequestException as exc:
            wait = 2 ** attempt
            logger.warning("Finnhub-Fehler (Versuch %d): %s – Warte %ds", attempt + 1, exc, wait)
            time.sleep(wait)

    return []


def _simple_sentiment(text: str) -> float:
    """
    Sehr einfaches keyword-basiertes Sentiment (-1 bis 1).
    Kann durch einen echten Sentiment-Classifier ersetzt werden.
    """
    positive = {"gain", "surge", "rise", "growth", "profit", "beat", "record", "strong", "up", "bull"}
    negative = {"loss", "drop", "fall", "decline", "miss", "weak", "cut", "down", "bear", "crash"}
    words = set(text.lower().split())
    pos = len(words & positive)
    neg = len(words & negative)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


# ---------------------------------------------------------------------------
# Wirtschaftskalender via Investing.com
# ---------------------------------------------------------------------------

def fetch_economic_calendar(url: str = None, min_impact: str = "MEDIUM") -> list[dict]:
    """
    Scrapet den Investing.com Wirtschaftskalender.
    Gibt Liste von Events zurück: {time, impact, title, actual, forecast, previous}
    Fällt bei Scraping-Fehler auf eine leere Liste zurück.
    """
    if url is None:
        url = "https://www.investing.com/economic-calendar/"

    impact_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    min_level = impact_order.get(min_impact.upper(), 2)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
        "X-Requested-With": "XMLHttpRequest",
    }

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            events = _parse_calendar(soup, min_level, impact_order)
            logger.info("Wirtschaftskalender: %d Events geladen", len(events))
            return events
        except requests.RequestException as exc:
            wait = 2 ** attempt
            logger.warning("Kalender-Fehler (Versuch %d): %s – Warte %ds", attempt + 1, exc, wait)
            time.sleep(wait)
        except Exception as exc:
            logger.error("Kalender-Parse-Fehler: %s", exc)
            return []

    return []


def _parse_calendar(soup: BeautifulSoup, min_level: int, impact_order: dict) -> list[dict]:
    """Parst die HTML-Tabelle des Investing.com-Kalenders."""
    events = []
    table = soup.find("table", {"id": "economicCalendarData"})
    if not table:
        return events

    for row in table.find_all("tr", class_="js-event-item"):
        try:
            time_cell = row.find("td", class_="time")
            event_time = time_cell.text.strip() if time_cell else ""

            bull_icons = row.find_all("i", class_="grayFullBullishIcon")
            impact_level = len(bull_icons)
            impact_map = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}
            impact = impact_map.get(impact_level, "LOW")

            if impact_order.get(impact, 1) < min_level:
                continue

            title_cell = row.find("td", class_="event")
            title = title_cell.text.strip() if title_cell else ""
            if not title:
                continue

            actual = _cell_text(row, "actual")
            forecast = _cell_text(row, "forecast")
            previous = _cell_text(row, "prev")

            events.append({
                "time": event_time,
                "impact": impact,
                "title": title,
                "actual": actual,
                "forecast": forecast,
                "previous": previous,
            })
        except Exception:
            continue

    return events


def _cell_text(row, class_name: str) -> str:
    cell = row.find("td", class_=class_name)
    return cell.text.strip() if cell else ""


# ---------------------------------------------------------------------------
# Intraday-Schleife
# ---------------------------------------------------------------------------

def run_intraday_loop(
    conn: sqlite3.Connection,
    tickers: list[str],
    cfg: dict,
    stop_at: str = None,
    simulator=None,
) -> None:
    """
    Läuft in einer Schleife (alle interval_sec Sekunden) bis zur Marktschlusszeit.
    Holt OHLCV → berechnet Indikatoren → prüft Signale → lädt News.

    simulator: optionale PaperTradingSimulator-Instanz. Wenn übergeben, wird
               nach jeder Ticker-Aktualisierung on_tick() aufgerufen.
    """
    from src.db import upsert_prices, upsert_indicators, insert_signal, insert_news
    from src.signal_logic import check_all_signals

    interval_sec = cfg.get("market_hours", {}).get("intraday_interval_sec", 300)
    market_close = stop_at or cfg.get("market_hours", {}).get("close", "22:00")
    finnhub_key = cfg.get("finnhub", {}).get("api_key", "")

    logger.info("Starte Intraday-Loop. Marktschluss: %s. Interval: %ds", market_close, interval_sec)
    if simulator and simulator.enabled:
        logger.info("Paper-Trading-Simulator aktiv (Modi: %s)", ", ".join(simulator.portfolios))

    while True:
        now_str = datetime.now().strftime("%H:%M")
        if now_str >= market_close:
            logger.info("Marktschluss erreicht (%s) – Intraday-Loop beendet", now_str)
            break

        tick_timestamp = datetime.now().isoformat(timespec="seconds")

        for ticker in tickers:
            try:
                df = fetch_ohlcv(ticker, cfg.get("yfinance", {}).get("interval", "5m"),
                                  cfg.get("yfinance", {}).get("period", "5d"))
                if df is None:
                    continue

                upsert_prices(conn, ticker, df)

                df_ind = compute_indicators(df, cfg)
                upsert_indicators(conn, ticker, df_ind)

                # Signale nur auf den letzten 2 Balken prüfen (aktueller + vorheriger).
                # Die gesamte Historie wurde bei früheren Ticks bereits verarbeitet.
                df_recent = df_ind.tail(2)
                signals = check_all_signals(df_recent, ticker, cfg)
                for sig in signals:
                    insert_signal(conn, sig)

                news = fetch_news_sentiment(ticker, finnhub_key)
                if news:
                    insert_news(conn, news)

                # --- Paper-Trading: aktuellen Preis + neue Signale weiterleiten ---
                if simulator and simulator.enabled and not df.empty:
                    # Spaltennamen normalisieren
                    close_col = [c for c in df.columns if str(c).lower() in ("close", "close")]
                    if close_col:
                        current_price = float(df[close_col[0]].iloc[-1])
                    else:
                        current_price = float(df.iloc[-1, 3])  # 4. Spalte = Close

                    simulator.on_tick(
                        ticker=ticker,
                        current_price=current_price,
                        signals=signals,
                        timestamp=tick_timestamp,
                    )

            except Exception as exc:
                logger.error("Fehler bei Ticker %s: %s", ticker, exc)

        logger.debug("Schleifendurchlauf abgeschlossen. Warte %ds …", interval_sec)
        time.sleep(interval_sec)

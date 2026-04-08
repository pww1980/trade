"""
db.py – SQLite-Datenbankinitialisierung und Hilfsfunktionen.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS prices (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker    TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open      REAL,
    high      REAL,
    low       REAL,
    close     REAL,
    volume    INTEGER,
    UNIQUE(ticker, timestamp)
);

CREATE TABLE IF NOT EXISTS indicators (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    sma_fast      REAL,
    sma_slow      REAL,
    ema_fast      REAL,
    rsi           REAL,
    macd          REAL,
    macd_signal   REAL,
    macd_hist     REAL,
    bb_upper      REAL,
    bb_middle     REAL,
    bb_lower      REAL,
    stoch_k       REAL,
    stoch_d       REAL,
    obv           REAL,
    vwap          REAL,
    volume_avg20  REAL,
    UNIQUE(ticker, timestamp)
);

CREATE TABLE IF NOT EXISTS signals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker           TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    signal_type      TEXT NOT NULL,
    strategy         TEXT NOT NULL,
    strength         REAL,
    price_at_signal  REAL,
    rsi_at_signal    REAL,
    eod_return_pct   REAL,
    outcome          TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date  TEXT NOT NULL,
    event_time  TEXT,
    impact      TEXT,
    title       TEXT NOT NULL,
    actual      TEXT,
    forecast    TEXT,
    previous    TEXT
);

CREATE TABLE IF NOT EXISTS news_sentiment (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    headline        TEXT,
    sentiment_score REAL,
    source          TEXT
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    """Öffnet/erstellt die SQLite-DB, legt Tabellen an und gibt Connection zurück."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(DDL)
    conn.commit()
    logger.info("Datenbank initialisiert: %s", db_path)
    return conn


def upsert_prices(conn: sqlite3.Connection, ticker: str, df: pd.DataFrame) -> None:
    """Schreibt OHLCV-DataFrame in Tabelle prices (INSERT OR REPLACE)."""
    rows = [
        (ticker, str(ts), row["Open"], row["High"], row["Low"], row["Close"], int(row["Volume"]))
        for ts, row in df.iterrows()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO prices (ticker, timestamp, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    logger.debug("prices: %d Zeilen für %s gespeichert", len(rows), ticker)


def upsert_indicators(conn: sqlite3.Connection, ticker: str, df: pd.DataFrame) -> None:
    """Schreibt Indikatoren-DataFrame in Tabelle indicators."""
    col_map = {
        "sma_fast": "sma_fast", "sma_slow": "sma_slow", "ema_fast": "ema_fast",
        "rsi": "rsi", "macd": "macd", "macd_signal": "macd_signal", "macd_hist": "macd_hist",
        "bb_upper": "bb_upper", "bb_middle": "bb_middle", "bb_lower": "bb_lower",
        "stoch_k": "stoch_k", "stoch_d": "stoch_d",
        "obv": "obv", "vwap": "vwap", "volume_avg20": "volume_avg20",
    }

    def _get(row, key):
        return float(row[key]) if key in row.index and pd.notna(row[key]) else None

    rows = [
        (ticker, str(ts), *[_get(row, k) for k in col_map])
        for ts, row in df.iterrows()
    ]
    cols = ", ".join(col_map.keys())
    placeholders = ", ".join(["?"] * (2 + len(col_map)))
    conn.executemany(
        f"INSERT OR REPLACE INTO indicators (ticker, timestamp, {cols}) VALUES ({placeholders})",
        rows,
    )
    conn.commit()
    logger.debug("indicators: %d Zeilen für %s gespeichert", len(rows), ticker)


def insert_signal(conn: sqlite3.Connection, signal: dict) -> None:
    """Fügt ein Signal in die Tabelle signals ein."""
    conn.execute(
        "INSERT INTO signals (ticker, timestamp, signal_type, strategy, strength, "
        "price_at_signal, rsi_at_signal) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            signal["ticker"], signal["timestamp"], signal["signal_type"],
            signal["strategy"], signal.get("strength"), signal.get("price"),
            signal.get("rsi"),
        ),
    )
    conn.commit()
    logger.info("Signal: %s %s @ %s (Stärke %.2f)", signal["signal_type"], signal["ticker"],
                signal["timestamp"], signal.get("strength", 0))


def insert_news(conn: sqlite3.Connection, records: list[dict]) -> None:
    """Fügt News-Sentiment-Einträge ein."""
    conn.executemany(
        "INSERT OR IGNORE INTO news_sentiment (ticker, timestamp, headline, sentiment_score, source) "
        "VALUES (?, ?, ?, ?, ?)",
        [(r["ticker"], r["timestamp"], r.get("headline"), r.get("sentiment"), r.get("source")) for r in records],
    )
    conn.commit()


def insert_events(conn: sqlite3.Connection, events: list[dict], event_date: str) -> None:
    """Fügt Wirtschaftskalender-Ereignisse ein."""
    conn.executemany(
        "INSERT OR IGNORE INTO events (event_date, event_time, impact, title, actual, forecast, previous) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(event_date, e.get("time"), e.get("impact"), e["title"],
          e.get("actual"), e.get("forecast"), e.get("previous")) for e in events],
    )
    conn.commit()


def update_eod_returns(conn: sqlite3.Connection, trade_date: str) -> None:
    """
    Berechnet für alle Signale des Handelstages den EOD-Return (Close-to-Close)
    und setzt das Outcome (WIN / LOSS / FLAT).
    """
    # Hole Signals ohne Return
    cursor = conn.execute(
        "SELECT id, ticker, price_at_signal FROM signals "
        "WHERE date(timestamp) = ? AND eod_return_pct IS NULL",
        (trade_date,),
    )
    rows = cursor.fetchall()

    for row in rows:
        sig_id, ticker, entry_price = row["id"], row["ticker"], row["price_at_signal"]
        if entry_price is None:
            continue
        # Letzter Close des Tages
        eod = conn.execute(
            "SELECT close FROM prices WHERE ticker = ? AND date(timestamp) = ? ORDER BY timestamp DESC LIMIT 1",
            (ticker, trade_date),
        ).fetchone()
        if eod is None:
            continue
        ret_pct = (eod["close"] - entry_price) / entry_price * 100
        outcome = "WIN" if ret_pct > 0.1 else ("LOSS" if ret_pct < -0.1 else "FLAT")
        conn.execute(
            "UPDATE signals SET eod_return_pct = ?, outcome = ? WHERE id = ?",
            (round(ret_pct, 4), outcome, sig_id),
        )
    conn.commit()
    logger.info("EOD-Returns berechnet für %d Signale (%s)", len(rows), trade_date)


def get_daily_performance(conn: sqlite3.Connection, trade_date: str) -> dict:
    """Aggregiert Tages-Kennzahlen aus der DB."""
    sigs = conn.execute(
        "SELECT signal_type, strength, eod_return_pct, outcome, ticker, timestamp, "
        "price_at_signal, rsi_at_signal, strategy "
        "FROM signals WHERE date(timestamp) = ?",
        (trade_date,),
    ).fetchall()

    if not sigs:
        return {"trade_date": trade_date, "total_signals": 0}

    returns = [s["eod_return_pct"] for s in sigs if s["eod_return_pct"] is not None]
    wins = [r for r in returns if r > 0.1]
    losses = [r for r in returns if r < -0.1]

    hit_rate = len(wins) / len(returns) if returns else 0.0
    avg_return = sum(returns) / len(returns) if returns else 0.0
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Max Drawdown (kumulativ)
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in returns:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Information Coefficient (Korrelation Signalstärke ↔ Return)
    strengths = [s["strength"] for s in sigs if s["strength"] is not None and s["eod_return_pct"] is not None]
    rets_for_ic = [s["eod_return_pct"] for s in sigs if s["strength"] is not None and s["eod_return_pct"] is not None]
    ic = _pearson(strengths, rets_for_ic)

    events = conn.execute(
        "SELECT event_time, impact, title, actual, forecast FROM events WHERE event_date = ?",
        (trade_date,),
    ).fetchall()

    news = conn.execute(
        "SELECT ticker, sentiment_score, headline FROM news_sentiment "
        "WHERE date(timestamp) = ? ORDER BY ticker, timestamp DESC",
        (trade_date,),
    ).fetchall()

    return {
        "trade_date": trade_date,
        "total_signals": len(sigs),
        "winning_signals": len(wins),
        "hit_rate": hit_rate,
        "avg_return_pct": avg_return,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_dd,
        "information_coefficient": ic,
        "signals": [dict(s) for s in sigs],
        "events": [dict(e) for e in events],
        "news": [dict(n) for n in news],
    }


def _pearson(x: list, y: list) -> Optional[float]:
    """Einfacher Pearson-Korrelationskoeffizient."""
    n = len(x)
    if n < 2:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den = (sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y)) ** 0.5
    return round(num / den, 4) if den != 0 else None

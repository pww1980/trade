"""
trade_simulator.py – Paper-Trading-Simulation mit drei parallelen Modi.

Modi:
  conservative  – 5 % Positionsgröße, max 3 Positionen, enger Stop-Loss
  normal        – 10 % Positionsgröße, max 5 Positionen, moderater Stop-Loss
  risk          – 25 % Positionsgröße, max 8 Positionen, weiter Stop-Loss

Alle drei Modi laufen parallel (threading.Thread) und teilen sich
die eingehenden Preisdaten und Signale, haben aber völlig getrennte
Portfolios und Trade-Historien.
"""

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Modus-Konfigurationen (Defaults; werden durch config.yaml überschrieben)
# ---------------------------------------------------------------------------

DEFAULT_MODE_CONFIGS: dict[str, dict] = {
    "conservative": {
        "max_position_pct": 0.05,   # max 5 % des Portfoliowerts pro Position
        "max_positions": 3,
        "stop_loss_pct": 0.02,      # 2 % unter Einstiegspreis
        "take_profit_pct": 0.05,    # 5 % über Einstiegspreis
        "min_signal_strength": 0.8, # nur sehr starke Signale handeln
        "commission_pct": 0.001,    # 0,1 % Transaktionskosten
    },
    "normal": {
        "max_position_pct": 0.10,
        "max_positions": 5,
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.08,
        "min_signal_strength": 0.6,
        "commission_pct": 0.001,
    },
    "risk": {
        "max_position_pct": 0.25,
        "max_positions": 8,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.15,
        "min_signal_strength": 0.4,
        "commission_pct": 0.001,
    },
}


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class Position:
    ticker: str
    shares: float
    avg_entry_price: float
    entry_date: str
    stop_loss_price: float
    take_profit_price: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * (self.current_price or self.avg_entry_price)

    @property
    def unrealized_pnl(self) -> float:
        return self.shares * ((self.current_price or self.avg_entry_price) - self.avg_entry_price)

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_entry_price == 0:
            return 0.0
        return (self.current_price - self.avg_entry_price) / self.avg_entry_price * 100


@dataclass
class Portfolio:
    """Ein vollständiges Paper-Trading-Portfolio für einen Modus."""

    mode: str
    cash: float
    starting_capital: float
    mode_cfg: dict
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)
    _prev_total_value: float = 0.0  # für tägliche P&L-Berechnung

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def positions_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_value(self) -> float:
        return self.cash + self.positions_value

    @property
    def total_pnl(self) -> float:
        return self.total_value - self.starting_capital

    @property
    def total_pnl_pct(self) -> float:
        return self.total_pnl / self.starting_capital * 100 if self.starting_capital else 0.0

    # ------------------------------------------------------------------
    # Preis-Update
    # ------------------------------------------------------------------

    def update_price(self, ticker: str, price: float) -> None:
        """Aktualisiert den Marktpreis einer offenen Position."""
        if ticker in self.positions:
            self.positions[ticker].current_price = price

    # ------------------------------------------------------------------
    # Stop-Loss / Take-Profit-Prüfung
    # ------------------------------------------------------------------

    def check_stops(self, ticker: str, current_price: float, timestamp: str) -> Optional[dict]:
        """Prüft Stop-Loss / Take-Profit und schließt Position bei Auslösung."""
        if ticker not in self.positions:
            return None
        pos = self.positions[ticker]
        pos.current_price = current_price

        if current_price <= pos.stop_loss_price:
            logger.info("[%s] STOP-LOSS ausgelöst: %s @ %.4f (SL=%.4f)",
                        self.mode, ticker, current_price, pos.stop_loss_price)
            return self._execute_sell(ticker, current_price, timestamp, "STOP_LOSS")

        if current_price >= pos.take_profit_price:
            logger.info("[%s] TAKE-PROFIT ausgelöst: %s @ %.4f (TP=%.4f)",
                        self.mode, ticker, current_price, pos.take_profit_price)
            return self._execute_sell(ticker, current_price, timestamp, "TAKE_PROFIT")

        return None

    # ------------------------------------------------------------------
    # Kauf
    # ------------------------------------------------------------------

    def buy(self, ticker: str, price: float, timestamp: str, reason: str,
            signal_strength: float = 1.0) -> Optional[dict]:
        """Öffnet eine neue Position. Gibt Trade-Dict oder None zurück."""
        min_strength = self.mode_cfg.get("min_signal_strength", 0.6)
        if signal_strength < min_strength:
            logger.debug("[%s] Signal %s zu schwach (%.2f < %.2f) – kein Kauf",
                         self.mode, ticker, signal_strength, min_strength)
            return None

        if ticker in self.positions:
            logger.debug("[%s] %s bereits im Portfolio – kein Doppelkauf", self.mode, ticker)
            return None

        max_pos = self.mode_cfg.get("max_positions", 5)
        if len(self.positions) >= max_pos:
            logger.debug("[%s] Max. Positionen (%d) erreicht – kein Kauf", self.mode, max_pos)
            return None

        max_invest = self.total_value * self.mode_cfg.get("max_position_pct", 0.10)
        comm_rate = self.mode_cfg.get("commission_pct", 0.001)

        # Anteile berechnen
        shares = int(max_invest / (price * (1 + comm_rate)))
        if shares <= 0:
            return None

        total_cost = shares * price * (1 + comm_rate)
        if total_cost > self.cash:
            shares = int(self.cash / (price * (1 + comm_rate)))
            total_cost = shares * price * (1 + comm_rate)

        if shares <= 0:
            logger.debug("[%s] Nicht genug Cash für %s (Cash=%.2f, Preis=%.2f)",
                         self.mode, ticker, self.cash, price)
            return None

        commission = shares * price * comm_rate
        self.cash -= total_cost

        sl = price * (1 - self.mode_cfg.get("stop_loss_pct", 0.03))
        tp = price * (1 + self.mode_cfg.get("take_profit_pct", 0.08))

        self.positions[ticker] = Position(
            ticker=ticker,
            shares=float(shares),
            avg_entry_price=price,
            entry_date=timestamp[:10],
            stop_loss_price=round(sl, 4),
            take_profit_price=round(tp, 4),
            current_price=price,
        )

        trade = self._make_trade_record(ticker, "BUY", shares, price, commission, None, reason, timestamp)
        self.trades.append(trade)
        logger.info("[%s] KAUF: %d x %s @ %.4f | SL=%.4f | TP=%.4f | Cash=%.2f",
                    self.mode, shares, ticker, price, sl, tp, self.cash)
        return trade

    # ------------------------------------------------------------------
    # Verkauf (Signal)
    # ------------------------------------------------------------------

    def sell(self, ticker: str, price: float, timestamp: str, reason: str) -> Optional[dict]:
        """Schließt eine offene Position auf Signal-Basis."""
        return self._execute_sell(ticker, price, timestamp, reason)

    # ------------------------------------------------------------------
    # EOD: alle Positionen zum aktuellen Marktpreis schließen
    # (optional – wir halten Positionen über Nacht)
    # ------------------------------------------------------------------

    def close_all_positions_eod(self, prices: dict[str, float], timestamp: str) -> list[dict]:
        """Schließt am Tagesende alle Positionen zum letzten Preis (nur wenn gewünscht)."""
        closed = []
        for ticker in list(self.positions.keys()):
            price = prices.get(ticker, self.positions[ticker].avg_entry_price)
            t = self._execute_sell(ticker, price, timestamp, "EOD_CLOSE")
            if t:
                closed.append(t)
        return closed

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _execute_sell(self, ticker: str, price: float, timestamp: str, reason: str) -> Optional[dict]:
        if ticker not in self.positions:
            return None
        pos = self.positions.pop(ticker)
        comm_rate = self.mode_cfg.get("commission_pct", 0.001)
        commission = pos.shares * price * comm_rate
        proceeds = pos.shares * price - commission
        realized_pnl = proceeds - (pos.shares * pos.avg_entry_price)

        self.cash += proceeds

        trade = self._make_trade_record(
            ticker, "SELL", pos.shares, price, commission, round(realized_pnl, 4), reason, timestamp
        )
        self.trades.append(trade)
        logger.info("[%s] VERKAUF: %.0f x %s @ %.4f | PnL=%.2f | Cash=%.2f",
                    self.mode, pos.shares, ticker, price, realized_pnl, self.cash)
        return trade

    def _make_trade_record(self, ticker, action, shares, price, commission, realized_pnl, reason, timestamp) -> dict:
        return {
            "mode": self.mode,
            "ticker": ticker,
            "trade_date": timestamp[:10],
            "trade_time": timestamp[11:16] if len(timestamp) > 10 else "?",
            "action": action,
            "shares": float(shares),
            "price": round(price, 4),
            "value": round(shares * price, 4),
            "commission": round(commission, 4),
            "realized_pnl": realized_pnl,
            "reason": reason,
            "cash_after": round(self.cash, 4),
            "portfolio_value_after": round(self.total_value, 4),
        }

    def summary(self, trade_date: str) -> dict:
        """Gibt Tages-Zusammenfassung als Dict zurück."""
        return {
            "mode": self.mode,
            "trade_date": trade_date,
            "starting_capital": round(self.starting_capital, 4),
            "cash": round(self.cash, 4),
            "positions_value": round(self.positions_value, 4),
            "total_value": round(self.total_value, 4),
            "total_pnl": round(self.total_pnl, 4),
            "total_pnl_pct": round(self.total_pnl_pct, 4),
            "num_trades": len(self.trades),
            "open_positions": len(self.positions),
            "positions": [
                {
                    "ticker": p.ticker,
                    "shares": p.shares,
                    "avg_entry_price": p.avg_entry_price,
                    "current_price": p.current_price,
                    "stop_loss_price": p.stop_loss_price,
                    "take_profit_price": p.take_profit_price,
                    "unrealized_pnl": round(p.unrealized_pnl, 4),
                    "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 4),
                    "market_value": round(p.market_value, 4),
                }
                for p in self.positions.values()
            ],
            "trades": self.trades,
        }


# ---------------------------------------------------------------------------
# Simulator – koordiniert alle drei Modi
# ---------------------------------------------------------------------------

class PaperTradingSimulator:
    """
    Koordiniert drei parallele Portfolio-Instanzen.

    Auf jeden on_tick()-Aufruf werden alle drei Modi sequentiell
    (keine Threads nötig) in wenigen Millisekunden durchlaufen.
    Das Threading wird nur für die Datenbankpersistenz am Tagesende genutzt.
    """

    def __init__(self, cfg: dict, conn: sqlite3.Connection, trade_date: str):
        self.cfg = cfg
        self.conn = conn
        self.trade_date = trade_date
        self._lock = threading.Lock()

        pt_cfg = cfg.get("paper_trading", {})
        self.enabled = pt_cfg.get("enabled", True)
        self._latest_prices: dict[str, float] = {}

        if not self.enabled:
            self.portfolios = {}
            return

        mode_cfgs = _build_mode_configs(cfg)
        self.portfolios = self._init_portfolios(pt_cfg, mode_cfgs)

    # ------------------------------------------------------------------
    # Initialisierung: vorhandene Positionen aus DB laden
    # ------------------------------------------------------------------

    def _init_portfolios(self, pt_cfg: dict, mode_cfgs: dict[str, dict]) -> dict[str, Portfolio]:
        from src.db import load_portfolio_state, load_open_positions

        starting_capital = pt_cfg.get("starting_capital", 10_000.0)
        portfolios = {}

        for mode, mcfg in mode_cfgs.items():
            state = load_portfolio_state(self.conn, mode, self.trade_date)
            if state:
                cash = state["cash"]
                start_cap = state["starting_capital"]
                logger.info("[%s] Vorhandenen Portfolio-Stand geladen: %.2f cash", mode, cash)
            else:
                # Versuche Stand vom Vortag zu laden
                prev = load_latest_portfolio_state(self.conn, mode)
                if prev:
                    cash = prev["cash"]
                    start_cap = prev["starting_capital"]
                    logger.info("[%s] Vortagsstand geladen: %.2f total_value", mode, prev["total_value"])
                else:
                    cash = starting_capital
                    start_cap = starting_capital
                    logger.info("[%s] Neues Portfolio mit %.2f Startkapital", mode, starting_capital)

            p = Portfolio(
                mode=mode,
                cash=cash,
                starting_capital=start_cap,
                mode_cfg=mcfg,
            )

            # Offene Positionen aus DB laden (Übernacht-Positionen)
            open_pos = load_open_positions(self.conn, mode)
            for pos_dict in open_pos:
                p.positions[pos_dict["ticker"]] = Position(
                    ticker=pos_dict["ticker"],
                    shares=pos_dict["shares"],
                    avg_entry_price=pos_dict["avg_entry_price"],
                    entry_date=pos_dict["entry_date"],
                    stop_loss_price=pos_dict["stop_loss_price"],
                    take_profit_price=pos_dict["take_profit_price"],
                    current_price=pos_dict.get("current_price") or pos_dict["avg_entry_price"],
                )
            if open_pos:
                logger.info("[%s] %d Übernacht-Positionen geladen", mode, len(open_pos))

            portfolios[mode] = p

        return portfolios

    # ------------------------------------------------------------------
    # Tick-Verarbeitung (wird nach jeder Preis-Aktualisierung aufgerufen)
    # ------------------------------------------------------------------

    def on_tick(self, ticker: str, current_price: float, signals: list[dict], timestamp: str) -> None:
        """
        Verarbeitet eine Preis-Aktualisierung für alle drei Modi.

        signals: Liste von Signal-Dicts aus signal_logic.check_all_signals()
        """
        if not self.enabled or not self.portfolios:
            return

        self._latest_prices[ticker] = current_price

        # Alle drei Modi sequentiell (schnell, kein IO)
        for mode, portfolio in self.portfolios.items():
            # 1. Stop-Loss / Take-Profit prüfen
            portfolio.check_stops(ticker, current_price, timestamp)

            # 2. Neue Signale verarbeiten
            for sig in signals:
                if sig.get("ticker") != ticker:
                    continue
                stype = sig.get("signal_type", "")
                strength = sig.get("strength", 0.0) or 0.0

                if stype == "BUY":
                    portfolio.buy(
                        ticker=ticker,
                        price=current_price,
                        timestamp=timestamp,
                        reason=sig.get("strategy", "SIGNAL"),
                        signal_strength=strength,
                    )
                elif stype == "SELL":
                    portfolio.sell(
                        ticker=ticker,
                        price=current_price,
                        timestamp=timestamp,
                        reason=sig.get("strategy", "SIGNAL"),
                    )

            # 3. Preis aktualisieren
            portfolio.update_price(ticker, current_price)

    # ------------------------------------------------------------------
    # Tagesabschluss: Persistenz in DB
    # ------------------------------------------------------------------

    def close_day(self) -> dict[str, dict]:
        """
        Speichert alle Portfolio-Zustände und Trades in die DB.
        Gibt Zusammenfassung aller Modi zurück.
        """
        if not self.enabled or not self.portfolios:
            return {}

        from src.db import save_portfolio_state, save_trades, upsert_paper_positions

        summaries = {}
        threads = []

        def _persist(mode: str, portfolio: Portfolio) -> None:
            summary = portfolio.summary(self.trade_date)
            with self._lock:
                save_portfolio_state(self.conn, summary)
                save_trades(self.conn, portfolio.trades)
                upsert_paper_positions(self.conn, mode, list(portfolio.positions.values()))
            summaries[mode] = summary
            logger.info("[%s] Tagesabschluss: total_value=%.2f, PnL=%.2f (%.2f%%)",
                        mode, summary["total_value"], summary["total_pnl"], summary["total_pnl_pct"])

        for mode, portfolio in self.portfolios.items():
            t = threading.Thread(target=_persist, args=(mode, portfolio), name=f"persist-{mode}", daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=30)

        return summaries

    # ------------------------------------------------------------------
    # Tages-Zusammenfassung für PDF
    # ------------------------------------------------------------------

    def get_summaries(self) -> dict[str, dict]:
        """Gibt aktuelle In-Memory-Zusammenfassung aller Modi zurück."""
        return {
            mode: portfolio.summary(self.trade_date)
            for mode, portfolio in self.portfolios.items()
        }


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _build_mode_configs(cfg: dict) -> dict[str, dict]:
    """Baut Mode-Konfigurationen aus config.yaml, mit Defaults als Fallback."""
    pt_cfg = cfg.get("paper_trading", {})
    user_modes = pt_cfg.get("modes", {})
    global_commission = pt_cfg.get("commission_pct", 0.001)

    result = {}
    for mode, defaults in DEFAULT_MODE_CONFIGS.items():
        merged = dict(defaults)
        merged.update(user_modes.get(mode, {}))
        merged.setdefault("commission_pct", global_commission)
        result[mode] = merged

    return result


def load_latest_portfolio_state(conn: sqlite3.Connection, mode: str) -> Optional[dict]:
    """Lädt den neuesten Portfolio-Stand (egal welches Datum) aus der DB."""
    row = conn.execute(
        "SELECT * FROM paper_portfolio WHERE mode = ? ORDER BY trade_date DESC LIMIT 1",
        (mode,),
    ).fetchone()
    return dict(row) if row else None

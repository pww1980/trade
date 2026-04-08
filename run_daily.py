#!/usr/bin/env python3
"""
run_daily.py – Hauptskript des End-of-Day Trading Systems.

Verwendung:
  python run_daily.py                # alle drei Phasen
  python run_daily.py --premarket    # nur Vormarkt (Wirtschaftskalender)
  python run_daily.py --intraday     # nur Intraday-Loop (bis Marktschluss)
  python run_daily.py --postmarket   # nur Postmarkt (Returns, KI, PDF)
  python run_daily.py --date 2026-04-07  # anderen Handelstag verwenden
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Konfiguration laden
# ---------------------------------------------------------------------------

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Logging einrichten
# ---------------------------------------------------------------------------

def setup_logging(cfg: dict) -> None:
    log_dir = Path(cfg.get("log_dir", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date.today()}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


logger = logging.getLogger("run_daily")


# ---------------------------------------------------------------------------
# Phasen
# ---------------------------------------------------------------------------

def phase_premarket(conn, cfg: dict, trade_date: str) -> None:
    """Lädt Wirtschaftskalender und speichert Events in der DB."""
    from src.data_fetch import fetch_economic_calendar
    from src.db import insert_events

    logger.info("=== PHASE: VORMARKT (%s) ===", trade_date)
    cal_cfg = cfg.get("investing_calendar", {})
    url = cal_cfg.get("url")
    min_impact = cal_cfg.get("min_impact", "MEDIUM")

    events = fetch_economic_calendar(url=url, min_impact=min_impact)
    insert_events(conn, events, trade_date)
    logger.info("Vormarkt abgeschlossen. %d Events gespeichert.", len(events))


def phase_intraday(conn, cfg: dict) -> None:
    """Startet die Intraday-Schleife (blockiert bis Marktschluss)."""
    from src.data_fetch import run_intraday_loop

    tickers = cfg.get("tickers", [])
    if not tickers:
        logger.error("Keine Tickers konfiguriert. Bitte config.yaml anpassen.")
        return

    logger.info("=== PHASE: INTRADAY-LOOP (%d Tickers) ===", len(tickers))
    run_intraday_loop(conn, tickers, cfg)
    logger.info("Intraday-Loop beendet.")


def phase_postmarket(conn, cfg: dict, trade_date: str) -> str:
    """
    Berechnet EOD-Returns, holt KI-Analyse und erstellt PDF.
    Gibt PDF-Pfad zurück.
    """
    from src.ai_verifier import verify_signals
    from src.pdf_report import generate_report

    logger.info("=== PHASE: POSTMARKT (%s) ===", trade_date)

    ai_summary = verify_signals(conn, trade_date, cfg)
    logger.info("KI-Analyse abgeschlossen.")

    pdf_path = generate_report(conn, trade_date, ai_summary, cfg)
    logger.info("PDF erstellt: %s", pdf_path)
    return pdf_path


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-of-Day Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--premarket", action="store_true", help="Nur Vormarkt-Phase")
    parser.add_argument("--intraday", action="store_true", help="Nur Intraday-Loop")
    parser.add_argument("--postmarket", action="store_true", help="Nur Postmarkt-Phase")
    parser.add_argument("--date", default=str(date.today()), help="Handelsdatum (YYYY-MM-DD)")
    parser.add_argument("--config", default="config.yaml", help="Pfad zur Konfigurationsdatei")
    args = parser.parse_args()

    # Konfiguration
    if not Path(args.config).exists():
        print(f"FEHLER: Konfigurationsdatei nicht gefunden: {args.config}")
        sys.exit(1)

    cfg = load_config(args.config)
    setup_logging(cfg)

    trade_date = args.date
    logger.info("Trading-System gestartet. Handelstag: %s", trade_date)

    # Datenbank
    from src.db import init_db
    db_path = Path(cfg.get("data_dir", "./data")) / cfg.get("db_name", "trading.db")
    conn = init_db(str(db_path))

    # Bestimme welche Phasen laufen sollen
    run_all = not (args.premarket or args.intraday or args.postmarket)

    try:
        if args.premarket or run_all:
            phase_premarket(conn, cfg, trade_date)

        if args.intraday or run_all:
            phase_intraday(conn, cfg)

        if args.postmarket or run_all:
            pdf_path = phase_postmarket(conn, cfg, trade_date)
            print(f"\nReport gespeichert: {pdf_path}")

        logger.info("Trading-System erfolgreich beendet.")

    except KeyboardInterrupt:
        logger.info("Abbruch durch Benutzer (Strg+C).")
    except Exception as exc:
        logger.exception("Unbehandelter Fehler: %s", exc)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

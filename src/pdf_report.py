"""
pdf_report.py – Tages-PDF-Report via ReportLab.

Seite 1: KPI-Boxen | Wirtschaftskalender | Signaltabelle
Seite 2: Performance-Details | KI-Analyse | Verbesserungsvorschläge | Disclaimer
Seite 3: Paper-Trading-Ergebnisse (Conservative / Normal / Risk im Vergleich)
"""

import logging
import os
from datetime import datetime
from pathlib import Path
import sqlite3

# ReportLab-Konstante vorab laden (wird in Hilfsfunktionen benötigt)
try:
    from reportlab.lib.units import cm as _CM
except ImportError:
    _CM = 28.35  # Fallback: 1 cm in Punkten

logger = logging.getLogger(__name__)

# Farben
COLOR_WIN = "#d4edda"
COLOR_LOSS = "#f8d7da"
COLOR_FLAT = "#f0f0f0"
COLOR_HEADER = "#343a40"
COLOR_ACCENT = "#0d6efd"
COLOR_TEXT = "#212529"


def generate_report(
    conn: sqlite3.Connection,
    trade_date: str,
    ai_summary: str,
    cfg: dict,
    paper_summaries: dict = None,
) -> str:
    """
    Erstellt das Tages-PDF und gibt den Dateipfad zurück.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, PageBreak,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    except ImportError:
        raise RuntimeError("reportlab nicht installiert. `pip install reportlab`")

    from src.db import get_daily_performance
    from src.ai_verifier import extract_suggestions

    perf = get_daily_performance(conn, trade_date)
    suggestions = extract_suggestions(ai_summary)

    output_dir = Path(cfg.get("output_dir", "./daily_reports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"{trade_date}.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor(COLOR_HEADER))
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor(COLOR_ACCENT))
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor(COLOR_TEXT))
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=7, textColor=colors.grey)
    center = ParagraphStyle("Center", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER)

    story = []
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ------------------------------------------------------------------ #
    # SEITE 1
    # ------------------------------------------------------------------ #

    # Header
    story.append(Paragraph("End-of-Day Trading Report", h1))
    story.append(Paragraph(f"Handelstag: {trade_date}  |  Erstellt: {gen_time}", small))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor(COLOR_ACCENT)))
    story.append(Spacer(1, 0.4 * cm))

    # KPI-Boxen (5er-Reihe)
    total = perf.get("total_signals", 0)
    hit_rate = perf.get("hit_rate", 0.0)
    avg_ret = perf.get("avg_return_pct", 0.0)
    pf = perf.get("profit_factor", 0.0)
    mdd = perf.get("max_drawdown_pct", 0.0)

    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"

    kpi_data = [
        [
            _kpi_cell("Signale", str(total)),
            _kpi_cell("Hit-Rate", f"{hit_rate:.1%}"),
            _kpi_cell("Avg. Return", f"{avg_ret:+.2f}%"),
            _kpi_cell("Profit-Factor", pf_str),
            _kpi_cell("Max. Drawdown", f"{mdd:.2f}%"),
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[3.2 * cm] * 5)
    kpi_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(COLOR_ACCENT)),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e9f0fb")),
        ("ROWHEIGHT", (0, 0), (-1, -1), 1.2 * cm),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 0.5 * cm))

    # Wirtschaftskalender
    story.append(Paragraph("Wirtschaftskalender", h2))
    events = perf.get("events", [])
    if events:
        ev_data = [["Zeit", "Impact", "Event", "Ist", "Prognose"]]
        for e in events[:15]:
            ev_data.append([
                e.get("event_time", "–"),
                e.get("impact", "–"),
                Paragraph(e.get("title", "–")[:60], body),
                e.get("actual", "–"),
                e.get("forecast", "–"),
            ])
        ev_table = Table(ev_data, colWidths=[1.5 * cm, 1.8 * cm, 8 * cm, 2 * cm, 2 * cm])
        ev_table.setStyle(_base_table_style())
        story.append(ev_table)
    else:
        story.append(Paragraph("Keine relevanten Events heute.", body))
    story.append(Spacer(1, 0.5 * cm))

    # Signaltabelle
    story.append(Paragraph("Signale des Tages", h2))
    signals = perf.get("signals", [])
    if signals:
        sig_data = [["Ticker", "Zeit", "Typ", "Strategie", "Preis", "RSI", "Return%", "Outcome"]]
        for s in signals:
            ret = s.get("eod_return_pct")
            ret_str = f"{ret:+.2f}" if ret is not None else "–"
            rsi = s.get("rsi_at_signal")
            rsi_str = f"{rsi:.1f}" if rsi is not None else "–"
            price = s.get("price_at_signal")
            price_str = f"{price:.2f}" if price is not None else "–"
            sig_data.append([
                s.get("ticker", "?"),
                str(s.get("timestamp", "?"))[:16],
                s.get("signal_type", "?"),
                (s.get("strategy") or "?")[:20],
                price_str,
                rsi_str,
                ret_str,
                s.get("outcome") or "–",
            ])

        col_w = [1.5 * cm, 3 * cm, 1.2 * cm, 4.5 * cm, 1.8 * cm, 1.2 * cm, 2 * cm, 1.5 * cm]
        sig_table = Table(sig_data, colWidths=col_w)
        style = _base_table_style()

        # Outcome-Einfärbung
        for i, s in enumerate(signals, start=1):
            outcome = s.get("outcome")
            if outcome == "WIN":
                bg = colors.HexColor(COLOR_WIN)
            elif outcome == "LOSS":
                bg = colors.HexColor(COLOR_LOSS)
            else:
                bg = colors.HexColor(COLOR_FLAT)
            style.add("BACKGROUND", (0, i), (-1, i), bg)

        sig_table.setStyle(style)
        story.append(sig_table)
    else:
        story.append(Paragraph("Keine Signale generiert.", body))

    # ------------------------------------------------------------------ #
    # SEITE 2
    # ------------------------------------------------------------------ #
    story.append(PageBreak())
    story.append(Paragraph("Performance-Details", h1))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor(COLOR_ACCENT)))
    story.append(Spacer(1, 0.3 * cm))

    ic = perf.get("information_coefficient")
    wins = perf.get("winning_signals", 0)

    perf_data = [
        ["Kennzahl", "Wert"],
        ["Handelstag", trade_date],
        ["Signale gesamt", str(total)],
        ["Gewinner", str(wins)],
        ["Verlierer", str(total - wins)],
        ["Hit-Rate", f"{hit_rate:.1%}"],
        ["Avg. Return", f"{avg_ret:+.2f}%"],
        ["Profit-Factor", pf_str],
        ["Max. Drawdown", f"{mdd:.2f}%"],
        ["Information Coefficient", f"{ic:.3f}" if ic is not None else "N/A"],
    ]
    perf_table = Table(perf_data, colWidths=[7 * cm, 7 * cm])
    perf_table.setStyle(_base_table_style())
    story.append(perf_table)
    story.append(Spacer(1, 0.5 * cm))

    # KI-Analyse
    ai_provider = cfg.get("ai_provider", "claude").capitalize()
    model_name = cfg.get(cfg.get("ai_provider", "claude"), {}).get("model", "")
    story.append(Paragraph(f"KI-Analyse ({ai_provider} / {model_name})", h2))
    story.append(Spacer(1, 0.2 * cm))

    # AI-Summary ohne den JSON-Block darstellen
    clean_summary = _strip_json_block(ai_summary)
    for para in clean_summary.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para.replace("\n", " "), body))
            story.append(Spacer(1, 0.2 * cm))

    # Verbesserungsvorschläge
    if suggestions:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("Verbesserungsvorschläge", h2))
        for i, sug in enumerate(suggestions, 1):
            story.append(Paragraph(f"{i}. {sug}", body))
            story.append(Spacer(1, 0.1 * cm))

    # Footer / Disclaimer
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "Haftungsausschluss: Dieser Bericht dient ausschließlich zu Informationszwecken "
        "und stellt keine Anlageberatung dar. Alle Angaben ohne Gewähr. "
        "Vergangene Performance ist kein Indikator für zukünftige Ergebnisse.",
        small,
    ))

    # ------------------------------------------------------------------ #
    # SEITE 3: Paper-Trading-Ergebnisse
    # ------------------------------------------------------------------ #
    if paper_summaries:
        story.append(PageBreak())
        _build_paper_trading_page(story, paper_summaries, trade_date, cfg,
                                  h1, h2, body, small, colors, cm, Table,
                                  TableStyle, HRFlowable, Spacer, Paragraph)

    doc.build(story)
    logger.info("PDF-Report erstellt: %s", pdf_path)
    return str(pdf_path)


# ---------------------------------------------------------------------------
# Paper-Trading-Seite
# ---------------------------------------------------------------------------

def _build_paper_trading_page(
    story, paper_summaries, trade_date, cfg,
    h1, h2, body, small, colors, cm, Table,
    TableStyle, HRFlowable, Spacer, Paragraph,
):
    """Baut Seite 3 des PDFs: Paper-Trading-Vergleich aller drei Modi."""

    _ACCENT = COLOR_ACCENT  # Modul-Konstante
    MODE_LABELS = {
        "conservative": "Vorsichtig",
        "normal": "Normal",
        "risk": "Risiko",
    }
    MODE_COLORS = {
        "conservative": "#cce5ff",
        "normal": "#fff3cd",
        "risk": "#f8d7da",
    }
    COLOR_POSITIVE = "#28a745"
    COLOR_NEGATIVE = "#dc3545"

    story.append(Paragraph("Paper-Trading – Tagesergebnis", h1))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor(_ACCENT)))
    story.append(Spacer(1, 0.3 * cm))

    pt_cfg = cfg.get("paper_trading", {})
    starting_capital = pt_cfg.get("starting_capital", 10_000.0)

    # ---- Vergleichstabelle (alle Modi nebeneinander) ----
    story.append(Paragraph("Portfolio-Vergleich", h2))
    story.append(Spacer(1, 0.2 * cm))

    header = ["Kennzahl", "Vorsichtig", "Normal", "Risiko"]
    modes_order = ["conservative", "normal", "risk"]

    def _val(mode, key, fmt=None):
        d = paper_summaries.get(mode, {})
        v = d.get(key)
        if v is None:
            return "–"
        return fmt(v) if fmt else str(v)

    sign = lambda v: f"+{v:.2f}" if v >= 0 else f"{v:.2f}"
    signpct = lambda v: f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"

    compare_data = [
        header,
        ["Startkapital", f"{starting_capital:,.2f}", f"{starting_capital:,.2f}", f"{starting_capital:,.2f}"],
        ["Portfolio-Wert",
         _val("conservative", "total_value", lambda v: f"{v:,.2f}"),
         _val("normal", "total_value", lambda v: f"{v:,.2f}"),
         _val("risk", "total_value", lambda v: f"{v:,.2f}")],
        ["Gesamt-P&L",
         _val("conservative", "total_pnl", sign),
         _val("normal", "total_pnl", sign),
         _val("risk", "total_pnl", sign)],
        ["Gesamt-P&L %",
         _val("conservative", "total_pnl_pct", signpct),
         _val("normal", "total_pnl_pct", signpct),
         _val("risk", "total_pnl_pct", signpct)],
        ["Cash",
         _val("conservative", "cash", lambda v: f"{v:,.2f}"),
         _val("normal", "cash", lambda v: f"{v:,.2f}"),
         _val("risk", "cash", lambda v: f"{v:,.2f}")],
        ["Offene Positionen",
         _val("conservative", "open_positions"),
         _val("normal", "open_positions"),
         _val("risk", "open_positions")],
        ["Trades heute",
         _val("conservative", "num_trades"),
         _val("normal", "num_trades"),
         _val("risk", "num_trades")],
    ]

    cmp_table = Table(compare_data, colWidths=[4.5 * cm, 4 * cm, 4 * cm, 4 * cm])
    cmp_style = _base_table_style()
    # Modus-Spalten einfärben
    for col_idx, mode in enumerate(modes_order, start=1):
        cmp_style.add("BACKGROUND", (col_idx, 1), (col_idx, -1),
                      colors.HexColor(MODE_COLORS.get(mode, "#ffffff")))
    cmp_table.setStyle(cmp_style)
    story.append(cmp_table)
    story.append(Spacer(1, 0.6 * cm))

    # ---- Detail-Abschnitt je Modus ----
    for mode in modes_order:
        d = paper_summaries.get(mode)
        if not d:
            continue

        label = MODE_LABELS.get(mode, mode.capitalize())
        mode_color = MODE_COLORS.get(mode, "#ffffff")

        story.append(Paragraph(f"Modus: {label}", h2))

        # Konfigurationszeile
        mode_cfg_data = cfg.get("paper_trading", {}).get("modes", {}).get(mode, {})
        cfg_line = (
            f"Max. Position: {mode_cfg_data.get('max_position_pct', '?') * 100:.0f}%  |  "
            f"Max. Positionen: {mode_cfg_data.get('max_positions', '?')}  |  "
            f"Stop-Loss: {mode_cfg_data.get('stop_loss_pct', 0) * 100:.0f}%  |  "
            f"Take-Profit: {mode_cfg_data.get('take_profit_pct', 0) * 100:.0f}%  |  "
            f"Min. Signalstärke: {mode_cfg_data.get('min_signal_strength', 0) * 100:.0f}%"
        )
        story.append(Paragraph(cfg_line, small))
        story.append(Spacer(1, 0.2 * cm))

        # Offene Positionen
        positions = d.get("positions", [])
        if positions:
            pos_data = [["Ticker", "Anteile", "Einstieg", "Aktuell", "SL", "TP", "Unreal. P&L", "Marktwert"]]
            for p in positions:
                upnl = p.get("unrealized_pnl") or 0
                upnl_pct = p.get("unrealized_pnl_pct") or 0
                pos_data.append([
                    p.get("ticker", "?"),
                    f"{p.get('shares', 0):.1f}",
                    f"{p.get('avg_entry_price', 0):.2f}",
                    f"{p.get('current_price') or p.get('avg_entry_price', 0):.2f}",
                    f"{p.get('stop_loss_price', 0):.2f}",
                    f"{p.get('take_profit_price', 0):.2f}",
                    f"{'+' if upnl >= 0 else ''}{upnl:.2f} ({upnl_pct:+.1f}%)",
                    f"{p.get('market_value', 0):.2f}",
                ])
            pos_table = Table(pos_data, colWidths=[1.5*cm, 1.5*cm, 2*cm, 2*cm, 2*cm, 2*cm, 3.5*cm, 2.5*cm])
            pos_style = _base_table_style()
            pos_style.add("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(mode_color))
            pos_style.add("TEXTCOLOR", (0, 0), (-1, 0), colors.black)
            pos_table.setStyle(pos_style)
            story.append(Paragraph("Offene Positionen:", body))
            story.append(pos_table)
            story.append(Spacer(1, 0.2 * cm))

        # Trades des Tages
        trades = d.get("trades", [])
        if trades:
            trade_data = [["Zeit", "Ticker", "Aktion", "Anteile", "Preis", "Wert", "P&L", "Grund"]]
            for t in trades:
                pnl = t.get("realized_pnl")
                pnl_str = f"{pnl:+.2f}" if pnl is not None else "–"
                trade_data.append([
                    t.get("trade_time", "?"),
                    t.get("ticker", "?"),
                    t.get("action", "?"),
                    f"{t.get('shares', 0):.1f}",
                    f"{t.get('price', 0):.2f}",
                    f"{t.get('value', 0):.2f}",
                    pnl_str,
                    (t.get("reason") or "–")[:18],
                ])
            trade_table = Table(
                trade_data,
                colWidths=[1.5*cm, 1.5*cm, 1.5*cm, 1.8*cm, 2*cm, 2.3*cm, 2.3*cm, 3*cm],
            )
            trade_style = _base_table_style()
            # BUY/SELL einfärben
            for i, t in enumerate(trades, start=1):
                if t.get("action") == "BUY":
                    trade_style.add("BACKGROUND", (2, i), (2, i), colors.HexColor(COLOR_WIN))
                elif t.get("action") == "SELL":
                    trade_style.add("BACKGROUND", (2, i), (2, i), colors.HexColor(COLOR_LOSS))
                # P&L einfärben
                pnl = t.get("realized_pnl")
                if pnl is not None:
                    col = COLOR_WIN if pnl >= 0 else COLOR_LOSS
                    trade_style.add("BACKGROUND", (6, i), (6, i), colors.HexColor(col))
            trade_table.setStyle(trade_style)
            story.append(Paragraph("Trades heute:", body))
            story.append(trade_table)
        else:
            story.append(Paragraph("Heute keine Trades ausgeführt.", body))

        story.append(Spacer(1, 0.5 * cm))


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _kpi_cell(label: str, value: str) -> str:
    """Gibt einen formatierten KPI-Zellen-String zurück."""
    return f"<b>{value}</b>\n{label}"


def _base_table_style() -> "TableStyle":
    from reportlab.platypus import TableStyle
    from reportlab.lib import colors
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_HEADER)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT", (0, 0), (-1, -1), 0.6 * _CM),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])


def _strip_json_block(text: str) -> str:
    """Entfernt den JSON-Suggestions-Block aus dem KI-Text."""
    idx = text.rfind('{"suggestions"')
    if idx != -1:
        text = text[:idx].strip()
    # Entferne ggf. abschließende Markdown-Codeblöcke
    if text.endswith("```"):
        text = text[: text.rfind("```")].strip()
    return text

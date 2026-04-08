"""
pdf_report.py – Tages-PDF-Report via ReportLab.

Seite 1: KPI-Boxen | Wirtschaftskalender | Signaltabelle
Seite 2: Performance-Details | KI-Analyse | Verbesserungsvorschläge | Disclaimer
"""

import logging
import os
from datetime import datetime
from pathlib import Path
import sqlite3

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

    doc.build(story)
    logger.info("PDF-Report erstellt: %s", pdf_path)
    return str(pdf_path)


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
        ("ROWHEIGHT", (0, 0), (-1, -1), 0.6 * cm),
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

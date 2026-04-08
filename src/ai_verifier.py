"""
ai_verifier.py – KI-Verifizierung der Tages-Signale via Claude oder OpenAI.
"""

import json
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt-Bau
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a professional quantitative analyst reviewing end-of-day trading performance.
Your job is to:
1. Evaluate the quality and coherence of today's technical trading signals.
2. Compare predicted signal direction with actual EOD returns.
3. Identify recurring patterns or systematic weaknesses in the strategy.
4. Provide a concise natural-language summary (3–5 paragraphs).
5. List up to 5 concrete, actionable improvement suggestions as a JSON array under the key "suggestions".

Be objective, specific, and avoid generic disclaimers.
Focus on what worked, what failed, and why.
At the end of your response, always include a JSON block in this exact format:
{"suggestions": ["suggestion 1", "suggestion 2", ...]}"""


def build_prompt(perf: dict, cfg: dict) -> str:
    """Erstellt den User-Message-Teil des Prompts aus den Performance-Kennzahlen."""
    trade_date = perf.get("trade_date", "N/A")
    total = perf.get("total_signals", 0)
    wins = perf.get("winning_signals", 0)
    hit_rate = perf.get("hit_rate", 0.0)
    avg_ret = perf.get("avg_return_pct", 0.0)
    pf = perf.get("profit_factor", 0.0)
    mdd = perf.get("max_drawdown_pct", 0.0)
    ic = perf.get("information_coefficient")
    signals = perf.get("signals", [])
    events = perf.get("events", [])
    news = perf.get("news", [])

    sc = cfg.get("signal", {})

    # Events-Abschnitt
    if events:
        events_text = "\n".join(
            f"  {e.get('event_time','?')} | {e.get('impact','?')} | {e.get('title','?')} "
            f"| Ist: {e.get('actual','–')} | Prognose: {e.get('forecast','–')}"
            for e in events
        )
    else:
        events_text = "  (Keine relevanten Events heute)"

    # Signale-Tabelle
    if signals:
        header = "  Ticker | Zeit | Typ | Strategie | Preis | RSI | Return% | Outcome"
        sep = "  " + "-" * 80
        rows = []
        for s in signals:
            rows.append(
                f"  {s.get('ticker','?'):6} | {str(s.get('timestamp','?'))[:16]} | "
                f"{s.get('signal_type','?'):4} | {s.get('strategy','?'):25} | "
                f"{s.get('price_at_signal') or '–':>8} | "
                f"{s.get('rsi_at_signal') or '–':>5} | "
                f"{s.get('eod_return_pct') or '–':>7} | "
                f"{s.get('outcome') or 'N/A'}"
            )
        signals_text = "\n".join([header, sep] + rows)
    else:
        signals_text = "  (Keine Signale heute)"

    # News-Sentiment-Zusammenfassung (pro Ticker aggregiert)
    if news:
        news_by_ticker: dict = {}
        for n in news:
            t = n.get("ticker", "?")
            if t not in news_by_ticker:
                news_by_ticker[t] = {"scores": [], "headlines": []}
            score = n.get("sentiment_score")
            if score is not None:
                news_by_ticker[t]["scores"].append(score)
            h = n.get("headline")
            if h:
                news_by_ticker[t]["headlines"].append(h)

        news_lines = []
        for t, data in news_by_ticker.items():
            avg_score = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0.0
            top = data["headlines"][0] if data["headlines"] else "–"
            news_lines.append(
                f"  {t}: Avg-Sentiment={avg_score:+.2f} ({len(data['headlines'])} Headlines) | Top: \"{top[:80]}\""
            )
        news_text = "\n".join(news_lines)
    else:
        news_text = "  (Kein Sentiment verfügbar)"

    ic_str = f"{ic:.3f}" if ic is not None else "N/A"
    pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"

    prompt = f"""=== TRADING PERFORMANCE REPORT — {trade_date} ===

--- WIRTSCHAFTSKALENDER (MEDIUM/HIGH Impact Events) ---
{events_text}

--- SIGNAL-ZUSAMMENFASSUNG ---
  Signale gesamt:          {total}
  Gewinner (Return > 0%):  {wins}
  Hit-Rate:                {hit_rate:.1%}
  Durchschnittlicher Ret.: {avg_ret:+.2f}%
  Profit-Factor:           {pf_str}
  Max. Drawdown:           {mdd:.2f}%
  Information Coefficient: {ic_str}

--- EINZELNE SIGNALE ---
{signals_text}

--- NEWS-SENTIMENT ---
{news_text}

--- AKTUELLE INDIKATOR-PARAMETER ---
  SMA fast/slow:         {sc.get('sma_fast', 20)}/{sc.get('sma_slow', 50)}
  RSI-Schwelle:          {sc.get('rsi_threshold', 50)}
  MACD-Bestätigung:      {sc.get('macd_signal', True)}
  OBV steigend:          {sc.get('obv_rising', True)}
  Volumen-Multiplikator: {sc.get('volume_multiplier', 1.5)}x

Bitte analysiere die obigen Daten und erstelle dein Fazit."""

    return prompt


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

def call_claude(user_prompt: str, cfg: dict) -> str:
    """Ruft die Claude API auf und gibt die Antwort als String zurück."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic-Paket nicht installiert. `pip install anthropic`")

    claude_cfg = cfg.get("claude", {})
    api_key = claude_cfg.get("api_key", "")
    model = claude_cfg.get("model", "claude-sonnet-4-6")
    max_tokens = claude_cfg.get("max_tokens", 4096)

    if not api_key or api_key == "ANTHROPIC_API_KEY":
        raise ValueError("Claude API-Key nicht konfiguriert (config.yaml → claude.api_key)")

    client = anthropic.Anthropic(api_key=api_key)

    logger.info("Sende Anfrage an Claude (%s) …", model)

    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        message = stream.get_final_message()

    response_text = message.content[0].text if message.content else ""
    logger.info(
        "Claude-Antwort erhalten. Input-Tokens: %d, Output-Tokens: %d",
        message.usage.input_tokens,
        message.usage.output_tokens,
    )
    return response_text


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def call_openai(user_prompt: str, cfg: dict) -> str:
    """Ruft die OpenAI API auf und gibt die Antwort zurück."""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai-Paket nicht installiert. `pip install openai`")

    openai_cfg = cfg.get("openai", {})
    api_key = openai_cfg.get("api_key", "")
    model = openai_cfg.get("model", "gpt-4o")
    max_tokens = openai_cfg.get("max_tokens", 4096)

    if not api_key or api_key == "OPENAI_API_KEY":
        raise ValueError("OpenAI API-Key nicht konfiguriert (config.yaml → openai.api_key)")

    client = OpenAI(api_key=api_key)
    logger.info("Sende Anfrage an OpenAI (%s) …", model)

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    text = response.choices[0].message.content or ""
    logger.info("OpenAI-Antwort erhalten. Tokens: %d", response.usage.total_tokens)
    return text


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def verify_signals(conn: sqlite3.Connection, trade_date: str, cfg: dict) -> str:
    """
    Hauptfunktion: Liest Performance-Daten, baut Prompt, ruft KI auf.
    Gibt KI-Antwort als String zurück (oder Fallback-Text bei Fehler).
    """
    from src.db import get_daily_performance, update_eod_returns

    update_eod_returns(conn, trade_date)
    perf = get_daily_performance(conn, trade_date)

    if perf.get("total_signals", 0) == 0:
        return "Heute wurden keine Signale generiert. Keine KI-Analyse verfügbar."

    user_prompt = build_prompt(perf, cfg)
    provider = cfg.get("ai_provider", "claude").lower()

    try:
        if provider == "claude":
            return call_claude(user_prompt, cfg)
        elif provider in ("chatgpt", "openai"):
            return call_openai(user_prompt, cfg)
        else:
            logger.error("Unbekannter AI-Provider: %s", provider)
            return f"Unbekannter AI-Provider '{provider}'. Bitte 'claude' oder 'chatgpt' wählen."
    except Exception as exc:
        logger.error("KI-Fehler: %s", exc)
        return f"KI-Analyse konnte nicht erstellt werden: {exc}"


def extract_suggestions(ai_response: str) -> list[str]:
    """Extrahiert das JSON-Suggestions-Array aus der KI-Antwort."""
    try:
        start = ai_response.rfind('{"suggestions"')
        if start == -1:
            start = ai_response.rfind("```json")
            if start != -1:
                start = ai_response.find("{", start)
        if start == -1:
            return []
        end = ai_response.find("}", start) + 1
        data = json.loads(ai_response[start:end])
        return data.get("suggestions", [])
    except (json.JSONDecodeError, ValueError):
        return []

"""
signal_logic.py – Regelbasierte Signalgenerierung aus berechneten Indikatoren.
"""

import logging
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_signal_strength(conditions: list[bool]) -> float:
    """Gibt den Anteil erfüllter Bedingungen als Zahl zwischen 0.0 und 1.0 zurück."""
    if not conditions:
        return 0.0
    return round(sum(conditions) / len(conditions), 4)


def generate_signal(row: pd.Series, cfg: dict) -> Optional[dict]:
    """
    Prüft eine Indikatoren-Zeile gegen die konfigurierten Signalregeln.

    Strategie GOLDEN_CROSS_RSI_OBV (BUY):
      - SMA_fast > SMA_slow  (Golden Cross)
      - RSI < rsi_threshold
      - MACD-Histogramm > 0  (wenn macd_signal=true)
      - OBV steigt           (wenn obv_rising=true)
      - Volumen > Durchschnitt * Multiplikator

    Gibt ein Signal-Dict zurück oder None.
    """
    sc = cfg.get("signal", {})
    sma_fast_th = sc.get("sma_fast", 20)
    sma_slow_th = sc.get("sma_slow", 50)
    rsi_thresh = sc.get("rsi_threshold", 50)
    check_macd = sc.get("macd_signal", True)
    check_obv = sc.get("obv_rising", True)
    vol_mult = sc.get("volume_multiplier", 1.5)

    def _val(key):
        v = row.get(key)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    sma_fast = _val("sma_fast")
    sma_slow = _val("sma_slow")
    rsi = _val("rsi")
    macd_hist = _val("macd_hist")
    obv = _val("obv")
    obv_prev = _val("obv_prev")
    volume = _val("volume")
    volume_avg20 = _val("volume_avg20")
    close = _val("close")

    # Mindestanforderungen: SMA und RSI müssen vorhanden sein
    if any(v is None for v in [sma_fast, sma_slow, rsi, close]):
        return None

    conditions = []
    condition_names = []

    # 1. Golden Cross
    golden = sma_fast > sma_slow
    conditions.append(golden)
    condition_names.append(f"GoldenCross({sma_fast:.2f}>{sma_slow:.2f})")

    # 2. RSI unter Schwelle
    rsi_ok = rsi < rsi_thresh
    conditions.append(rsi_ok)
    condition_names.append(f"RSI<{rsi_thresh}({rsi:.1f})")

    # 3. MACD-Histogramm positiv
    if check_macd and macd_hist is not None:
        macd_ok = macd_hist > 0
        conditions.append(macd_ok)
        condition_names.append(f"MACD_hist>0({macd_hist:.4f})")

    # 4. OBV steigt
    if check_obv and obv is not None and obv_prev is not None:
        obv_ok = obv > obv_prev
        conditions.append(obv_ok)
        condition_names.append(f"OBV_rising({obv:.0f}>{obv_prev:.0f})")

    # 5. Volumen-Bestätigung
    if volume is not None and volume_avg20 is not None and volume_avg20 > 0:
        vol_ok = volume > volume_avg20 * vol_mult
        conditions.append(vol_ok)
        condition_names.append(f"Vol>{vol_mult}x({volume:.0f}>{volume_avg20*vol_mult:.0f})")

    strength = calculate_signal_strength(conditions)

    # Signal nur wenn alle Pflicht-Bedingungen erfüllt (Golden Cross + RSI)
    if not (golden and rsi_ok):
        return None

    # Mindestens 60% aller Bedingungen erfüllt
    if strength < 0.6:
        return None

    strategy = "GOLDEN_CROSS_RSI_OBV"
    logger.info(
        "BUY-Signal: %s Stärke=%.2f Bedingungen=[%s]",
        row.get("ticker", "?"), strength, ", ".join(condition_names),
    )

    return {
        "signal_type": "BUY",
        "strategy": strategy,
        "strength": strength,
        "price": close,
        "rsi": rsi,
        "conditions": condition_names,
    }


def generate_sell_signal(row: pd.Series, cfg: dict) -> Optional[dict]:
    """
    Einfache SELL-Signallogik (Death Cross oder RSI überkauft).
    """
    sc = cfg.get("signal", {})
    sma_fast_th = sc.get("sma_fast", 20)
    sma_slow_th = sc.get("sma_slow", 50)

    def _val(key):
        v = row.get(key)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else v

    sma_fast = _val("sma_fast")
    sma_slow = _val("sma_slow")
    rsi = _val("rsi")
    close = _val("close")

    if any(v is None for v in [sma_fast, sma_slow, rsi, close]):
        return None

    death_cross = sma_fast < sma_slow
    rsi_overbought = rsi > 70

    conditions = [death_cross, rsi_overbought]
    strength = calculate_signal_strength(conditions)

    if not (death_cross or rsi_overbought):
        return None

    return {
        "signal_type": "SELL",
        "strategy": "DEATH_CROSS_RSI_OVERBOUGHT",
        "strength": strength,
        "price": close,
        "rsi": rsi,
        "conditions": [f"DeathCross={death_cross}", f"RSI_overbought({rsi:.1f})={rsi_overbought}"],
    }


def check_all_signals(df: pd.DataFrame, ticker: str, cfg: dict) -> list[dict]:
    """
    Iteriert über alle Zeilen eines Indikatoren-DataFrames und gibt
    alle ausgelösten Signale als Liste zurück.
    """
    signals = []
    df = df.copy()
    df["ticker"] = ticker

    if "OBV" in df.columns:
        df["obv_prev"] = df["OBV"].shift(1)

    for ts, row in df.iterrows():
        row_dict = row.rename({
            "SMA_20": "sma_fast", "SMA_50": "sma_slow",
            f"EMA_20": "ema_fast",
            "RSI_14": "rsi",
            "MACD_12_26_9": "macd", "MACDs_12_26_9": "macd_signal", "MACDh_12_26_9": "macd_hist",
            "BBU_20_2.0": "bb_upper", "BBM_20_2.0": "bb_middle", "BBL_20_2.0": "bb_lower",
            "STOCHk_14_3_3": "stoch_k", "STOCHd_14_3_3": "stoch_d",
            "OBV": "obv", "VWAP_D": "vwap",
            "volume_avg20": "volume_avg20", "Volume": "volume", "Close": "close",
        })

        sig = generate_signal(row_dict, cfg)
        if sig:
            sig["ticker"] = ticker
            sig["timestamp"] = str(ts)
            signals.append(sig)
            continue  # Kein gleichzeitiges BUY+SELL

        sell = generate_sell_signal(row_dict, cfg)
        if sell:
            sell["ticker"] = ticker
            sell["timestamp"] = str(ts)
            signals.append(sell)

    return signals

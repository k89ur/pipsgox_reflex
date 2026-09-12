from __future__ import annotations

import numpy as np
import pandas as pd

QUALITY_SWING_RULES = {
    "Strict": {"window": 4, "min_swing_pct": 2.0, "min_bars": 5, "recovery_pct": 0.60},
    "Standard": {"window": 4, "min_swing_pct": 1.5, "min_bars": 4, "recovery_pct": 0.50},
    "Loose": {"window": 3, "min_swing_pct": 1.0, "min_bars": 3, "recovery_pct": 0.40},
}


def clean_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or not {"Close", "High", "Low", "Volume"}.issubset(frame.columns):
        return pd.DataFrame()
    x = frame[["Close", "High", "Low", "Volume"]].copy()
    x.index = pd.to_datetime(x.index, errors="coerce")
    if getattr(x.index, "tz", None) is not None:
        x.index = x.index.tz_localize(None)
    x = x[~x.index.isna()].sort_index()
    for c in x.columns:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).dropna(subset=["Close", "High", "Low"])
    x = x[x.Close > 0]
    x["Volume"] = x.Volume.fillna(0).clip(lower=0)
    return x


def detect_swings(frame: pd.DataFrame, quality: str = "Standard") -> list[dict]:
    """Return confirmed, meaningful alternating swing highs/lows."""
    x = clean_ohlcv(frame)
    if x.empty:
        return []
    rule = QUALITY_SWING_RULES.get(quality, QUALITY_SWING_RULES["Standard"])
    w, min_pct, min_bars = rule["window"], rule["min_swing_pct"], rule["min_bars"]
    hi = x.High.rolling(2 * w + 1, center=True).max()
    lo = x.Low.rolling(2 * w + 1, center=True).min()
    raw = []
    for i in range(w, len(x) - w):
        h, l = float(x.High.iloc[i]), float(x.Low.iloc[i])
        if h >= float(hi.iloc[i]) * (1 - 1e-9):
            raw.append({"i": i, "type": "H", "price": h, "date": x.index[i]})
        if l <= float(lo.iloc[i]) * (1 + 1e-9):
            raw.append({"i": i, "type": "L", "price": l, "date": x.index[i]})
    raw.sort(key=lambda p: (p["i"], 0 if p["type"] == "H" else 1))

    collapsed = []
    for p in raw:
        if not collapsed or collapsed[-1]["type"] != p["type"]:
            collapsed.append(p)
        else:
            old = collapsed[-1]
            more_extreme = p["price"] >= old["price"] if p["type"] == "H" else p["price"] <= old["price"]
            if more_extreme:
                collapsed[-1] = p

    swings = []
    for p in collapsed:
        if not swings:
            swings.append(p)
            continue
        prev = swings[-1]
        bars = p["i"] - prev["i"]
        move = abs(p["price"] - prev["price"]) / prev["price"] * 100 if prev["price"] else 0
        if bars < min_bars or move < min_pct:
            if p["type"] == prev["type"]:
                better = p["price"] >= prev["price"] if p["type"] == "H" else p["price"] <= prev["price"]
                if better:
                    swings[-1] = p
            continue
        swings.append(p)
    return swings


def build_contractions(frame: pd.DataFrame, quality: str = "Standard", lookback: int = 180) -> list[dict]:
    x = clean_ohlcv(frame)
    if x.empty:
        return []
    start = max(0, len(x) - lookback)
    y = x.iloc[start:].copy().reset_index(drop=False)
    swings = detect_swings(y, quality)
    rule = QUALITY_SWING_RULES.get(quality, QUALITY_SWING_RULES["Standard"])
    out = []
    for a, b, c in zip(swings, swings[1:], swings[2:]):
        if not (a["type"] == "H" and b["type"] == "L" and c["type"] == "H"):
            continue
        high, low, recovery = a["price"], b["price"], c["price"]
        depth = (high - low) / high * 100 if high else np.nan
        if not (1 <= depth <= 40):
            continue
        required_recovery = low + (high - low) * rule["recovery_pct"]
        if recovery < required_recovery:
            continue
        seg = y.iloc[a["i"]:c["i"] + 1]
        out.append({
            "high_i": start + a["i"], "low_i": start + b["i"], "recover_i": start + c["i"],
            "high": high, "low": low, "recovery_high": recovery, "depth": depth,
            "avg_volume": float(seg.Volume.mean()),
        })
    return out


def choose_longest_sequence(candidates: list[dict], minimum: int = 2, maximum: int = 4,
                            first_max: float = 25., final_max: float = 5., tolerance: float = .18) -> list[dict]:
    """Choose the longest valid 2–4 contraction sequence.

    Contraction depth does not have to shrink monotonically. The core setup
    permits later bases to remain within the broader first-contraction range;
    the 25% first-contraction cap and 5% final-contraction cap remain active.
    """
    best = []
    for end in range(len(candidates)):
        for start in range(max(0, end - maximum + 1), end + 1):
            seq = candidates[start:end + 1]
            if not minimum <= len(seq) <= maximum:
                continue
            if any(seq[k]["recover_i"] > seq[k + 1]["high_i"] for k in range(len(seq) - 1)):
                continue
            depths = [c["depth"] for c in seq]
            if depths[0] > first_max or depths[-1] > final_max:
                continue
            # Do not require artificial C1 > C2 > C3 > C4 progression.
            # Structural recovery highs must still remain meaningful.
            if any(seq[k + 1]["recovery_high"] < seq[k]["recovery_high"] * (0.75 - tolerance) for k in range(len(seq) - 1)):
                continue
            if len(seq) > len(best) or (len(seq) == len(best) and seq[-1]["recover_i"] > (best[-1]["recover_i"] if best else -1)):
                best = seq
    return best


def breakout_info(close: float, pivot: float, sequence: list[dict]) -> dict:
    if not sequence or not np.isfinite(pivot):
        return {"breakout": False, "status": "No VCP", "breakout_contractions": np.nan}
    breakout = close > pivot * 1.005
    distance = (pivot - close) / pivot * 100 if pivot else np.nan
    return {
        "breakout": breakout,
        "status": "Breakout" if breakout else ("Near Pivot" if 0 <= distance <= 5 else "Below Pivot"),
        "breakout_contractions": len(sequence) if breakout else np.nan,
    }

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

import rs_engine
from nse_latest_data import install_nse_latest_close

install_nse_latest_close(rs_engine)
DEFAULT_BATCH_SIZE = rs_engine.DEFAULT_BATCH_SIZE


# ---------------------------------------------------------------------------
# Simple VCP qualification model
# ---------------------------------------------------------------------------
# There is intentionally no swing/contraction, volume, breakout, quality,
# stage, score, pivot, or final-contraction logic in this version.


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
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


def _trend_values(x: pd.DataFrame):
    close = x.Close
    m50 = close.rolling(50).mean()
    m150 = close.rolling(150).mean()
    m200 = close.rolling(200).mean()
    if len(x) < 220 or any(pd.isna(v) for v in (m50.iloc[-1], m150.iloc[-1], m200.iloc[-1], m50.iloc[-21], m150.iloc[-21], m200.iloc[-21])):
        return None

    current = float(close.iloc[-1])
    vals = {
        "50DMA": float(m50.iloc[-1]),
        "150DMA": float(m150.iloc[-1]),
        "200DMA": float(m200.iloc[-1]),
        "50DMA Rising": bool(m50.iloc[-1] > m50.iloc[-21]),
        "150DMA Rising": bool(m150.iloc[-1] > m150.iloc[-21]),
        "200DMA Rising": bool(m200.iloc[-1] > m200.iloc[-21]),
    }
    vals["Trend OK"] = bool(
        current >= vals["50DMA"]
        and current >= vals["150DMA"]
        and current >= vals["200DMA"]
        and vals["50DMA Rising"]
        and vals["150DMA Rising"]
        and vals["200DMA Rising"]
    )
    return vals


def analyze_vcp(
    symbol,
    frame,
    trend_filter=True,
    use_52w_high=True,
    near_high_pct=5.0,
    use_52w_low=False,
    prior_low_pct=70.0,
    dma_position_filter=True,
    dma_position_pct=15.0,
):
    x = _clean(frame)
    if len(x) < 253:
        return {}

    close = float(x.Close.iloc[-1])
    range52 = x.iloc[-253:-1]
    high52 = float(range52.High.max())
    low52 = float(range52.Low.min())
    tv = _trend_values(x)
    if tv is None:
        return {}

    from_high = (close / high52 - 1.0) * 100 if high52 > 0 else np.nan
    from_low = (close / low52 - 1.0) * 100 if low52 > 0 else np.nan
    dma_distance = (close / tv["50DMA"] - 1.0) * 100 if tv["50DMA"] > 0 else np.nan

    high_ok = (not use_52w_high) or (np.isfinite(from_high) and from_high >= -float(near_high_pct))
    low_ok = (not use_52w_low) or (np.isfinite(from_low) and from_low >= float(prior_low_pct))
    trend_ok = tv["Trend OK"]
    dma_ok = (not dma_position_filter) or (
        np.isfinite(dma_distance) and abs(dma_distance) <= float(dma_position_pct)
    )
    qualified = bool(high_ok and low_ok and dma_ok and (trend_ok or not trend_filter))

    return {
        "Symbol": symbol,
        "LTP": close,
        "VCP": qualified,
        "52W High": high52,
        "From 52W High %": from_high,
        "52W Low": low52,
        "From 52W Low %": from_low,
        "50DMA": tv["50DMA"],
        "Price vs 50DMA %": dma_distance,
        "150DMA": tv["150DMA"],
        "200DMA": tv["200DMA"],
        "50DMA Rising": tv["50DMA Rising"],
        "150DMA Rising": tv["150DMA Rising"],
        "200DMA Rising": tv["200DMA Rising"],
        "Trend OK": trend_ok,
        "52W High OK": high_ok,
        "52W Low OK": low_ok,
        "50DMA Position OK": dma_ok,
        "History Days": len(x),
    }


def run_scan(
    trend_filter=True,
    use_52w_high=True,
    near_high_pct=5.0,
    use_52w_low=False,
    prior_low_pct=70.0,
    dma_position_filter=True,
    dma_position_pct=15.0,
    batch_size=DEFAULT_BATCH_SIZE,
    snapshot_mode="eod",
    force_refresh=False,
    progress_callback: Optional[Callable] = None,
):
    symbols = rs_engine.get_nse_symbols()
    snap = rs_engine._download_universe(
        symbols,
        batch_size=batch_size,
        snapshot_mode=snapshot_mode,
        force_refresh=force_refresh,
        progress_callback=progress_callback,
    )
    rows = []
    total = len(snap["data"])
    for done, (symbol, frame) in enumerate(snap["data"].items(), 1):
        try:
            r = analyze_vcp(
                symbol,
                frame,
                trend_filter=trend_filter,
                use_52w_high=use_52w_high,
                near_high_pct=near_high_pct,
                use_52w_low=use_52w_low,
                prior_low_pct=prior_low_pct,
                dma_position_filter=dma_position_filter,
                dma_position_pct=dma_position_pct,
            )
            if r:
                rows.append(r)
        except Exception:
            pass
        if progress_callback and (done == 1 or done % 100 == 0 or done == total):
            progress_callback(done, max(total, 1), f"Analysing VCP · {done:,}/{total:,}")

    if not rows:
        raise RuntimeError("No usable stock data was returned for VCP analysis.")

    df = pd.DataFrame(rows)
    df = df[df.VCP].copy().reset_index(drop=True)
    if not df.empty:
        meta = rs_engine._sector_industry_results(df.Symbol.astype(str).tolist())
        inds = rs_engine._stock_index_results(df.Symbol.astype(str).tolist())
        df["Industry"] = [meta.get(s, ("Not Available", "Not Available"))[1] for s in df.Symbol.astype(str)]
        df["Index"] = [
            " • ".join(v for v in inds.get(s, ("Not Available",) * 5) if v != "Not Available") or "Not Available"
            for s in df.Symbol.astype(str)
        ]

    df["TradingView"] = "https://www.tradingview.com/chart/?symbol=NSE%3A" + df.Symbol.astype(str)
    cols = [
        "Symbol", "Index", "Industry", "LTP",
        "52W High", "From 52W High %", "52W Low", "From 52W Low %",
        "50DMA", "Price vs 50DMA %", "150DMA", "200DMA",
        "50DMA Rising", "150DMA Rising", "200DMA Rising", "Trend OK",
        "52W High OK", "52W Low OK", "50DMA Position OK", "History Days", "TradingView",
    ]
    df = df[[c for c in cols if c in df.columns]]

    stats = {
        "universe": len(symbols),
        "downloaded": snap["downloaded"],
        "coverage": snap["usable_coverage"],
        "usable": snap["usable"],
        "missing_count": snap["missing_count"],
        "short_history_count": snap["short_history_count"],
        "stale_data_count": snap["stale_data_count"],
        "data_date": snap["data_date"],
        "snapshot_mode": snap["mode"],
        "snapshot_day": snap["snapshot_day"],
        "downloaded_at": snap["downloaded_at"],
        "total_candidates": len(rows),
        "matches": len(df),
    }
    return df, stats

# Deployment sync marker: keep UI and engine signatures aligned for the simplified VCP scanner.

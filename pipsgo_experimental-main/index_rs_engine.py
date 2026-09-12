from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import numpy as np
import pandas as pd
from tvDatafeed import TvDatafeed, Interval

INDEX_UNIVERSE = [
    ("BANKNIFTY", "BANKNIFTY"), ("CNXAUTO", "CNXAUTO"),
    ("CNXCONSUMPTION", "CNXCONSUMPTION"), ("CNXENERGY", "CNXENERGY"),
    ("CNXFINANCE", "CNXFINANCE"), ("CNXFMCG", "CNXFMCG"),
    ("CNXINFRA", "CNXINFRA"), ("CNXIT", "CNXIT"),
    ("CNXMETAL", "CNXMETAL"), ("CNXPHARMA", "CNXPHARMA"),
    ("CNXPSE", "CNXPSE"), ("CNXPSUBANK", "CNXPSUBANK"),
    ("CNXREALTY", "CNXREALTY"), ("CNXSERVICE", "CNXSERVICE"),
    ("CPSE", "CPSE"), ("NIFTYPVTBANK", "NIFTYPVTBANK"),
    ("NIFTY_CAPITAL_MKT", "NIFTY_CAPITAL_MKT"), ("NIFTY_CEMENT", "NIFTY_CEMENT"),
    ("NIFTY_CHEMICALS", "NIFTY_CHEMICALS"), ("NIFTY_CONSR_DURBL", "NIFTY_CONSR_DURBL"),
    ("NIFTY_EV", "NIFTY_EV"), ("NIFTY_HEALTHCARE", "NIFTY_HEALTHCARE"),
    ("NIFTY_IND_DEFENCE", "NIFTY_IND_DEFENCE"), ("NIFTY_IND_DIGITAL", "NIFTY_IND_DIGITAL"),
    ("NIFTY_IND_TOURISM", "NIFTY_IND_TOURISM"), ("NIFTY_IPO", "NIFTY_IPO"),
    ("NIFTY_OIL_AND_GAS", "NIFTY_OIL_AND_GAS"), ("NIFTY_TRANS_LOGIS", "NIFTY_TRANS_LOGIS"),
]
BENCHMARK_SYMBOL = "NIFTY"
EXCHANGE = "NSE"
BARS = 500
RETRY_BARS = 1000
REQUIRED_BARS = 253
AUDIT_INDEXES = ["CNXMETAL", "NIFTY_IND_DEFENCE", "NIFTY_IPO", "CNXENERGY"]


def _empty_result() -> pd.Series:
    return pd.Series(dtype=float)


def _fetch_tv(symbol: str, n_bars: int = BARS) -> pd.Series:
    try:
        tv = TvDatafeed()
        frame = tv.get_hist(symbol=symbol, exchange=EXCHANGE, interval=Interval.in_daily,
                            n_bars=n_bars, extended_session=False)
        if frame is None or frame.empty or "close" not in frame.columns:
            return _empty_result()
        close = pd.to_numeric(frame["close"], errors="coerce").dropna()
        if close.empty:
            return _empty_result()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close.sort_index().astype(float)
    except Exception:
        return _empty_result()


def _pine_score(close: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    calendar = benchmark.index.sort_values().unique()
    c = close.reindex(calendar).ffill()
    b = benchmark.reindex(calendar).ffill()
    periods = [("3M %", 63, 0.40), ("6M %", 126, 0.20), ("9M %", 189, 0.20), ("12M %", 252, 0.20)]
    result: dict[str, float] = {}
    total = 0.0
    for label, bars, weight in periods:
        if len(c) <= bars or len(b) <= bars:
            return {"3M %": np.nan, "6M %": np.nan, "9M %": np.nan, "12M %": np.nan, "Raw RS": np.nan}
        current_c, old_c = c.iloc[-1], c.iloc[-bars - 1]
        current_b, old_b = b.iloc[-1], b.iloc[-bars - 1]
        if any(pd.isna(v) for v in (current_c, old_c, current_b, old_b)) or old_c == 0 or old_b == 0:
            return {"3M %": np.nan, "6M %": np.nan, "9M %": np.nan, "12M %": np.nan, "Raw RS": np.nan}
        relative = ((float(current_c) / float(old_c) - 1.0) * 100.0) - ((float(current_b) / float(old_b) - 1.0) * 100.0)
        result[label] = relative
        total += relative * weight
    result["Raw RS"] = total
    return result


def _audit_points(close: pd.Series, benchmark: pd.Series, metrics: dict[str, float]) -> dict:
    calendar = benchmark.index.sort_values().unique()
    c = close.reindex(calendar).ffill()
    b = benchmark.reindex(calendar).ffill()
    points = [("3M", 63), ("6M", 126), ("9M", 189), ("12M", 252)]
    out = {"Index Current Date": c.index[-1], "Index Current Close": float(c.iloc[-1]),
           "Benchmark Current Date": b.index[-1], "Benchmark Current Close": float(b.iloc[-1])}
    for label, bars in points:
        idx = -bars - 1
        out[f"{label} Date"] = c.index[idx]
        out[f"{label} Index Close"] = float(c.iloc[idx])
        out[f"{label} Benchmark Close"] = float(b.iloc[idx])
        out[f"{label} Relative %"] = float(metrics[f"{label} %"])
    out["Raw RS"] = float(metrics["Raw RS"])
    return out


def _rating(value: float, scores: list[float]):
    valid = [x for x in scores if pd.notna(x)]
    if pd.isna(value) or len(valid) <= 1:
        return np.nan
    below = sum(x < value for x in valid)
    return int(round(1.0 + (below / (len(valid) - 1.0)) * 98.0))


def run_index_scan(progress_callback: Optional[Callable[[int, int, str], None]] = None):
    targets = [("__BENCHMARK__", BENCHMARK_SYMBOL)] + INDEX_UNIVERSE
    results: dict[str, pd.Series] = {}
    if progress_callback:
        progress_callback(0, len(targets), "Connecting to TradingView")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_tv, symbol): key for key, symbol in targets}
        completed = 0
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = _empty_result()
            completed += 1
            if progress_callback:
                progress_callback(completed, len(targets), "Downloading TradingView daily bars")

    benchmark = results.get("__BENCHMARK__", _empty_result())
    if benchmark.empty:
        raise RuntimeError("TradingView did not return NIFTY 50 daily bars. The anonymous TradingView data session may be temporarily limited; try Refresh RS once.")

    retry_keys = [key for key, _ in targets if key != "__BENCHMARK__" and (results.get(key, _empty_result()).empty or len(results.get(key, _empty_result())) < REQUIRED_BARS)]
    if retry_keys:
        if progress_callback:
            progress_callback(len(targets), len(targets), f"Retrying {len(retry_keys)} incomplete index series")
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_fetch_tv, dict(INDEX_UNIVERSE)[key], RETRY_BARS): key for key in retry_keys}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    retry = future.result()
                except Exception:
                    retry = _empty_result()
                if not retry.empty:
                    results[key] = retry

    benchmark_latest = benchmark.index[-1]
    rows = []
    audit_rows = []
    for alias, symbol in INDEX_UNIVERSE:
        close = results.get(alias, _empty_result())
        if close.empty:
            rows.append({"INDEX": alias, "TradingView": f"NSE:{symbol}", "Status": "Data unavailable", "Raw RS": np.nan, "Bars": 0, "First Date": pd.NaT, "Latest Date": pd.NaT})
            continue
        first_date = close.index[0]
        latest_date = close.index[-1]
        metrics = _pine_score(close, benchmark)
        if pd.isna(metrics["Raw RS"]):
            status = "Insufficient history"
        elif latest_date < benchmark_latest:
            status = f"Stale · {(benchmark_latest - latest_date).days}d"
        else:
            status = "OK"
        rows.append({"INDEX": alias, "TradingView": f"NSE:{symbol}", "LTP": float(close.iloc[-1]), **metrics,
                     "Bars": len(close), "First Date": first_date, "Latest Date": latest_date, "Status": status})
        if alias in AUDIT_INDEXES and pd.notna(metrics["Raw RS"]):
            audit_rows.append({"INDEX": alias, **_audit_points(close, benchmark, metrics)})

    df = pd.DataFrame(rows)
    scores = df["Raw RS"].tolist()
    df["RS 1-99"] = [_rating(float(x), scores) if pd.notna(x) else np.nan for x in scores]
    df = df.sort_values(["RS 1-99", "Raw RS"], ascending=False, na_position="last").reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))

    valid_dates = pd.to_datetime(df["Latest Date"], errors="coerce").dropna()
    stale_mask = df["Latest Date"].notna() & (pd.to_datetime(df["Latest Date"]) < benchmark_latest)
    return df, {
        "universe": len(INDEX_UNIVERSE),
        "available": int(df["Raw RS"].notna().sum()),
        "as_of": benchmark_latest,
        "benchmark_latest": benchmark_latest,
        "min_latest": valid_dates.min() if not valid_dates.empty else None,
        "max_latest": valid_dates.max() if not valid_dates.empty else None,
        "stale_count": int(stale_mask.sum()),
        "stale_symbols": df.loc[stale_mask, "INDEX"].tolist(),
        "unavailable_count": int(df["Latest Date"].isna().sum()),
        "audit_points": audit_rows,
        "source": "TradingView daily bars (same symbols as Pine)",
    }

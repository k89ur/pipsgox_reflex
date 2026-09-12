from __future__ import annotations

import io
import time
from collections import Counter
from datetime import datetime
from functools import lru_cache
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
SECTOR_INDUSTRY_URL = "https://drive.google.com/uc?export=download&id=1Auelz4iprUIV578TPc_C5i_EEol43i9c"
STOCK_INDEX_URL = "https://drive.google.com/uc?export=download&confirm=t&id=19auf-ZldcujlMEiznNUMYTFBiokST2ro"
DEFAULT_BATCH_SIZE = 100
MIN_SAFE_UNIVERSE_SIZE = 1000
IST = ZoneInfo("Asia/Kolkata")
_STOCK_DATA_CACHE: dict[tuple[str, str, tuple[str, ...], int], dict] = {}


def _normalize_symbol_list(values) -> list[str]:
    symbols = pd.Series(values, dtype="string").str.strip().str.upper()
    symbols = symbols.replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA, "SYMBOL": pd.NA}).dropna()
    return sorted(symbols.drop_duplicates().tolist())


def get_nse_symbols() -> list[str]:
    """Load a full NSE equity universe; never silently scan a tiny fallback list."""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"}
    nse_error = "unknown error"
    try:
        r = requests.get(NSE_URL, headers=headers, timeout=20)
        r.raise_for_status()
        if not r.content:
            raise ValueError("NSE returned an empty response")
        df = pd.read_csv(io.BytesIO(r.content))
        col = next((c for c in ["SYMBOL", "Symbol", "symbol"] if c in df.columns), None)
        if not col:
            raise ValueError("NSE CSV has no SYMBOL column")
        symbols = _normalize_symbol_list(df[col])
        if len(symbols) < MIN_SAFE_UNIVERSE_SIZE:
            raise ValueError(f"NSE universe is suspiciously small ({len(symbols):,} symbols)")
        return symbols
    except Exception as e:
        nse_error = str(e)

    try:
        fallback = pd.read_csv("symbols.csv")
        if fallback.empty or len(fallback.columns) == 0:
            raise ValueError("symbols.csv is empty")
        col = "Symbol" if "Symbol" in fallback.columns else fallback.columns[0]
        symbols = _normalize_symbol_list(fallback[col])
        if len(symbols) < MIN_SAFE_UNIVERSE_SIZE:
            raise ValueError(f"symbols.csv contains only {len(symbols):,} symbols")
        return symbols
    except Exception as fallback_error:
        raise RuntimeError(
            "NSE universe validation failed, so the scan was stopped to protect RS ranking integrity. "
            f"NSE source: {nse_error}. Fallback: {fallback_error}."
        ) from fallback_error


def _clean_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a downloaded symbol history before any row-based calculations."""
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.DataFrame()
    x = frame.copy()
    try:
        idx = pd.to_datetime(x.index, errors="coerce")
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        x.index = idx
        x = x[~x.index.isna()]
        x = x.sort_index()
        x = x[~x.index.duplicated(keep="last")]
    except Exception:
        return pd.DataFrame()
    x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
    if "High" in x.columns:
        x["High"] = pd.to_numeric(x["High"], errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan)
    x = x[x["Close"] > 0]
    return x


def _extract_downloaded(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return result
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        level1 = set(raw.columns.get_level_values(1))
        for s in symbols:
            t = f"{s}.NS"
            try:
                if t in level0:
                    x = raw[t].copy()
                elif t in level1:
                    x = raw.xs(t, axis=1, level=1).copy()
                else:
                    continue
                x = _clean_history(x)
                if not x.empty:
                    result[s] = x
            except Exception:
                continue
    else:
        s = symbols[0]
        if "Close" in raw.columns:
            x = _clean_history(raw)
            if not x.empty:
                result[s] = x
    return result


def _download_batch(symbols: list[str], retries: int = 3, threads: bool = True, period: str = "2y") -> dict[str, pd.DataFrame]:
    tickers = [f"{s}.NS" for s in symbols]
    last_result: dict[str, pd.DataFrame] = {}
    for attempt in range(retries):
        try:
            raw = yf.download(
                tickers=tickers,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=threads,
            )
            result = _extract_downloaded(raw, symbols)
            if len(result) == len(symbols):
                return result
            last_result = result
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(1.0 * (attempt + 1))
    return last_result


def _download_missing(symbols: list[str]) -> dict[str, pd.DataFrame]:
    recovered: dict[str, pd.DataFrame] = {}
    for start in range(0, len(symbols), 10):
        group = symbols[start:start + 10]
        recovered.update(_download_batch(group, retries=2, threads=False))
        if start + 10 < len(symbols):
            time.sleep(0.25)
    remaining = [symbol for symbol in symbols if symbol not in recovered]
    for symbol in remaining:
        recovered.update(_download_batch([symbol], retries=2, threads=False))
    return recovered


def _latest_date(frame: pd.DataFrame) -> Optional[str]:
    if frame is None or frame.empty:
        return None
    try:
        return pd.Timestamp(frame.index[-1]).date().isoformat()
    except Exception:
        return None


def _merge_history(old: pd.DataFrame, recent: pd.DataFrame) -> pd.DataFrame:
    """Merge a recent recovery window into the original long history."""
    if recent is None or recent.empty:
        return old
    if old is None or old.empty:
        return recent
    return _clean_history(pd.concat([old, recent], axis=0))


def _snapshot_date_diagnostics(data: dict[str, pd.DataFrame]) -> dict:
    latest_by_symbol: dict[str, str] = {}
    for symbol, frame in data.items():
        latest = _latest_date(frame)
        if latest:
            latest_by_symbol[symbol] = latest

    dates = list(latest_by_symbol.values())
    if not dates:
        return {
            "data_date": "Unknown",
            "min_data_date": "Unknown",
            "max_data_date": "Unknown",
            "date_consistent": False,
            "stale_data_count": 0,
            "stale_data_symbols": [],
            "date_distribution": {},
        }

    counts = Counter(dates)
    min_date = min(dates)
    max_date = max(dates)
    stale_symbols = sorted(symbol for symbol, date in latest_by_symbol.items() if date < max_date)
    distribution = dict(sorted(counts.items(), key=lambda item: item[0], reverse=True))
    return {
        "data_date": max_date,
        "min_data_date": min_date,
        "max_data_date": max_date,
        "date_consistent": min_date == max_date,
        "stale_data_count": len(stale_symbols),
        "stale_data_symbols": stale_symbols,
        "date_distribution": distribution,
    }


def _download_universe(symbols: list[str], batch_size: int = DEFAULT_BATCH_SIZE, snapshot_mode: str = "eod", force_refresh: bool = False, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> dict:
    """Download one market-data snapshot per mode and IST calendar day."""
    mode = str(snapshot_mode).lower().strip()
    if mode not in {"intraday", "eod"}:
        mode = "eod"
    snapshot_day = datetime.now(IST).date().isoformat()
    key = (mode, snapshot_day, tuple(symbols), batch_size)
    if not force_refresh and key in _STOCK_DATA_CACHE:
        cached = _STOCK_DATA_CACHE[key]
        if progress_callback:
            progress_callback(len(symbols), len(symbols), f"{mode.upper()} snapshot ready (cached)")
        return cached

    total = len(symbols)
    data: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    batch_count = (total + batch_size - 1) // batch_size
    for batch_no, start in enumerate(range(0, total, batch_size), start=1):
        batch = symbols[start:start + batch_size]
        if progress_callback:
            progress_callback(start, total, f"Downloading {mode.upper()} data · batch {batch_no}/{batch_count}")
        batch_data = _download_batch(batch)
        missing = [symbol for symbol in batch if symbol not in batch_data]
        if missing:
            batch_data.update(_download_missing(missing))
        unresolved = [symbol for symbol in batch if symbol not in batch_data]
        failed.extend(unresolved)
        data.update(batch_data)
        done = min(start + len(batch), total)
        if progress_callback:
            progress_callback(done, total, f"{mode.upper()} data · {len(data):,} received")

    # Bulk 2-year downloads can be complete but one trading day behind.
    # Recover the latest bars using a short recent window, then merge them into
    # the original 2-year histories. This avoids thousands of individual calls.
    initial_dates = [_latest_date(frame) for frame in data.values()]
    initial_dates = [date for date in initial_dates if date]
    target_date = max(initial_dates) if initial_dates else None
    stale_symbols = [symbol for symbol, frame in data.items() if target_date and _latest_date(frame) < target_date]
    if stale_symbols:
        total_stale = len(stale_symbols)
        if progress_callback:
            progress_callback(0, total_stale, f"Recovering {total_stale:,} stale symbols for {target_date}")
        recovery_batch_size = 50
        for start in range(0, total_stale, recovery_batch_size):
            group = stale_symbols[start:start + recovery_batch_size]
            recovered = _download_batch(group, retries=2, threads=True, period="10d")
            for symbol, recent in recovered.items():
                if _latest_date(recent) == target_date:
                    data[symbol] = _merge_history(data.get(symbol), recent)
            done = min(start + len(group), total_stale)
            if progress_callback:
                progress_callback(done, total_stale, f"Stale-data recovery · {done:,}/{total_stale:,}")
            if start + recovery_batch_size < total_stale:
                time.sleep(0.25)

    usable = [
        symbol
        for symbol, frame in data.items()
        if frame is not None
        and not frame.empty
        and "Close" in frame.columns
        and len(frame["Close"].dropna()) > 252
    ]
    usable_set = set(usable)
    missing = sorted(set(symbols) - set(data))
    date_diagnostics = _snapshot_date_diagnostics(data)
    stale_final = set(date_diagnostics["stale_data_symbols"])
    short_history = sorted((set(data) - usable_set) | stale_final)
    usable = [symbol for symbol in usable if symbol not in stale_final]
    snapshot = {
        "data": data,
        "downloaded_at": datetime.now(IST).isoformat(timespec="seconds"),
        "mode": mode,
        "snapshot_day": snapshot_day,
        "data_date": date_diagnostics["data_date"],
        "min_data_date": date_diagnostics["min_data_date"],
        "max_data_date": date_diagnostics["max_data_date"],
        "date_consistent": date_diagnostics["date_consistent"],
        "stale_data_count": date_diagnostics["stale_data_count"],
        "stale_data_symbols": date_diagnostics["stale_data_symbols"],
        "date_distribution": date_diagnostics["date_distribution"],
        "universe": total,
        "downloaded": len(data),
        "missing": missing,
        "missing_count": len(missing),
        "short_history": short_history,
        "short_history_count": len(short_history),
        "usable": len(usable),
        "usable_coverage": (len(usable) / total * 100) if total else 0,
    }
    _STOCK_DATA_CACHE[key] = snapshot
    if progress_callback:
        progress_callback(total, total, f"{mode.upper()} snapshot ready")
    return snapshot


def clear_stock_data_cache() -> None:
    _STOCK_DATA_CACHE.clear()


def _return_at_days(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        return np.nan
    now = float(close.iloc[-1])
    old = float(close.iloc[-days - 1])
    return (now / old - 1.0) * 100.0 if old else np.nan


def _metrics(symbol: str, x: pd.DataFrame, rising_days: int, calculate_ma_rising: bool = False, snapshot_mode: str = "eod") -> dict:
    close = x["Close"].dropna().astype(float)
    if len(close) < 200:
        return {}
    ltp = float(close.iloc[-1])
    d50 = close.rolling(50).mean()
    d150 = close.rolling(150).mean()
    d200 = close.rolling(200).mean()

    if "High" in x.columns:
        high = x["High"].dropna().astype(float)
        if len(high) < 253:
            return {}
        previous_52w_high = float(high.iloc[-253:-1].max())
        today_high = float(high.iloc[-1])
        high_52w = previous_52w_high
        from_high = (today_high - previous_52w_high) / previous_52w_high * 100.0 if previous_52w_high else np.nan
    else:
        high_52w = float(close.tail(252).max())
        from_high = (high_52w - ltp) / high_52w * 100.0 if high_52w else np.nan

    row = {
        "Symbol": symbol,
        "LTP": ltp,
        "3M %": _return_at_days(close, 63),
        "6M %": _return_at_days(close, 126),
        "9M %": _return_at_days(close, 189),
        "12M %": _return_at_days(close, 252),
        "50 DMA": float(d50.iloc[-1]),
        "150 DMA": float(d150.iloc[-1]),
        "200 DMA": float(d200.iloc[-1]),
        "52W High": high_52w,
        "From 52W High %": from_high,
        "History Days": len(close),
    }
    if calculate_ma_rising:
        if len(d200.dropna()) <= rising_days:
            return {}
        row.update({
            "50 DMA Rising": float(d50.iloc[-1]) > float(d50.iloc[-1 - rising_days]),
            "150 DMA Rising": float(d150.iloc[-1]) > float(d150.iloc[-1 - rising_days]),
            "200 DMA Rising": float(d200.iloc[-1]) > float(d200.iloc[-1 - rising_days]),
        })
    return row


def _percentile_rating(scores: pd.Series) -> pd.Series:
    pct = scores.rank(method="average", pct=True) * 99
    return pct.round().clip(1, 99).astype(int)


@lru_cache(maxsize=1)
def _load_sector_industry() -> dict[str, tuple[str, str]]:
    try:
        r = requests.get(SECTOR_INDUSTRY_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"}, timeout=30)
        r.raise_for_status()
        metadata = pd.read_csv(io.BytesIO(r.content))
        required = {"Symbol", "Sector", "Industry"}
        if not required.issubset(metadata.columns):
            raise ValueError("Sector/industry CSV is missing required columns")
        metadata = metadata[["Symbol", "Sector", "Industry"]].copy()
        metadata["Symbol"] = metadata["Symbol"].astype(str).str.strip().str.upper()
        for col in ["Sector", "Industry"]:
            metadata[col] = metadata[col].fillna("").astype(str).str.strip().replace("", "Not Available")
        metadata = metadata[~metadata["Symbol"].isin(["", "NAN", "NONE"])].drop_duplicates("Symbol")
        return {row.Symbol: (row.Sector, row.Industry) for row in metadata.itertuples(index=False)}
    except Exception:
        return {}


def _sector_industry_results(symbols: list[str]) -> dict[str, tuple[str, str]]:
    metadata = _load_sector_industry()
    return {symbol: metadata.get(symbol, ("Not Available", "Not Available")) for symbol in symbols}


def _load_stock_indices() -> dict[str, tuple[str, str, str, str, str]]:
    urls = [
        STOCK_INDEX_URL,
        "https://drive.google.com/uc?export=download&confirm=t&id=19auf-ZldcujlMEiznNUMYTFBiokST2ro",
        "https://drive.usercontent.google.com/download?id=19auf-ZldcujlMEiznNUMYTFBiokST2ro&export=download&confirm=t",
    ]
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/csv,application/octet-stream,*/*"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            r.raise_for_status()
            content = r.content
            if not content:
                continue
            metadata = pd.read_csv(io.BytesIO(content))
            normalized = {str(c).replace("\ufeff", "").strip().upper(): c for c in metadata.columns}
            symbol_col = normalized.get("SYMBOL")
            index_cols = [normalized.get(f"INDEX {i}") for i in range(1, 6)]
            if not symbol_col or any(c is None for c in index_cols):
                continue
            metadata = metadata[[symbol_col, *index_cols]].copy()
            metadata.columns = ["Symbol", "Index 1", "Index 2", "Index 3", "Index 4", "Index 5"]
            metadata["Symbol"] = metadata["Symbol"].astype(str).str.replace("\ufeff", "", regex=False).str.strip().str.upper()
            metadata = metadata[~metadata["Symbol"].isin(["", "NAN", "NONE"])].drop_duplicates("Symbol")
            for col in ["Index 1", "Index 2", "Index 3", "Index 4", "Index 5"]:
                metadata[col] = metadata[col].fillna("").astype(str).str.strip().replace("", "Not Available")
            return {row[0]: (row[1], row[2], row[3], row[4], row[5]) for row in metadata.itertuples(index=False, name=None)}
        except Exception:
            continue
    return {}


def _stock_index_results(symbols: list[str]) -> dict[str, tuple[str, str, str, str, str]]:
    metadata = _load_stock_indices()
    missing = ("Not Available",) * 5
    return {symbol: metadata.get(symbol, missing) for symbol in symbols}


def run_scan(min_rs: int = 80, near_high_pct: float = 5, min_price: float = 100, rising_days: int = 20, use_min_rs: bool = True, use_near_high: bool = True, use_min_price: bool = True, use_ma_rising: bool = False, use_minervini: bool = True, batch_size: int = DEFAULT_BATCH_SIZE, snapshot_mode: str = "eod", force_refresh: bool = False, progress_callback: Optional[Callable[[int, int, str], None]] = None):
    symbols = get_nse_symbols()
    total = len(symbols)
    snapshot = _download_universe(symbols, batch_size=batch_size, snapshot_mode=snapshot_mode, force_refresh=force_refresh, progress_callback=progress_callback)
    data = snapshot["data"]
    downloaded = snapshot["downloaded"]
    stale_set = set(snapshot["stale_data_symbols"])
    coverage = snapshot["usable_coverage"]
    rows = []
    for symbol, x in data.items():
        if symbol in stale_set:
            continue
        try:
            m = _metrics(symbol, x, rising_days, calculate_ma_rising=use_ma_rising, snapshot_mode=snapshot_mode)
            if m:
                rows.append(m)
        except Exception:
            continue
    if not rows:
        raise RuntimeError("No usable stock data was returned.")
    df = pd.DataFrame(rows)
    ret_cols = ["3M %", "6M %", "9M %", "12M %"]
    df = df.dropna(subset=ret_cols).copy()
    df["Raw RS Score"] = df["3M %"] * 0.40 + df["6M %"] * 0.20 + df["9M %"] * 0.20 + df["12M %"] * 0.20
    df["RS Rating"] = _percentile_rating(df["Raw RS Score"])
    if use_min_price:
        df = df[df["LTP"] >= min_price].copy()
    if use_near_high:
        df = df[df["From 52W High %"] >= -near_high_pct].copy()
    if use_min_rs:
        df = df[df["RS Rating"] >= min_rs].copy()
    if use_minervini:
        df = df[(df["LTP"] > df["50 DMA"]) & (df["LTP"] > df["150 DMA"]) & (df["LTP"] > df["200 DMA"])].copy()
    if use_ma_rising:
        df = df[df["50 DMA Rising"] & df["150 DMA Rising"] & df["200 DMA Rising"]].copy()
    df = df.sort_values(["RS Rating", "Raw RS Score"], ascending=False).reset_index(drop=True)
    if not df.empty:
        industry_metadata = _sector_industry_results(df["Symbol"].astype(str).tolist())
        index_metadata = _stock_index_results(df["Symbol"].astype(str).tolist())
        df["Industry"] = [industry_metadata.get(s, ("Not Available", "Not Available"))[1] for s in df["Symbol"].astype(str)]
        index_values = [index_metadata.get(s, ("Not Available",) * 5) for s in df["Symbol"].astype(str)]
        for i, col in enumerate(["Index 1", "Index 2", "Index 3", "Index 4", "Index 5"]):
            df[col] = [values[i] for values in index_values]
        df["Index"] = df[["Index 1", "Index 2", "Index 3", "Index 4", "Index 5"]].apply(lambda row: " • ".join(value for value in row if value != "Not Available") or "Not Available", axis=1)
        df = df.drop(columns=["Index 1", "Index 2", "Index 3", "Index 4", "Index 5"])
    else:
        df["Industry"] = pd.Series(dtype=str)
        df["Index"] = pd.Series(dtype=str)
    df["TradingView"] = "https://www.tradingview.com/chart/?symbol=NSE%3A" + df["Symbol"].astype(str)
    columns = ["Symbol", "Index", "Industry", "LTP", "RS Rating", "Raw RS Score", "3M %", "6M %", "9M %", "12M %", "52W High", "From 52W High %", "50 DMA", "150 DMA", "200 DMA", "50 DMA Rising", "150 DMA Rising", "200 DMA Rising", "History Days", "TradingView"]
    df = df[[c for c in columns if c in df.columns]]
    stats = {
        "universe": total,
        "downloaded": downloaded,
        "coverage": coverage,
        "downloaded_coverage": (downloaded / total * 100) if total else 0,
        "usable": snapshot["usable"],
        "usable_coverage": snapshot["usable_coverage"],
        "missing": snapshot["missing"],
        "missing_count": snapshot["missing_count"],
        "short_history": snapshot["short_history"],
        "short_history_count": snapshot["short_history_count"],
        "snapshot_mode": snapshot["mode"],
        "snapshot_day": snapshot["snapshot_day"],
        "data_date": snapshot["data_date"],
        "min_data_date": snapshot["min_data_date"],
        "max_data_date": snapshot["max_data_date"],
        "date_consistent": snapshot["date_consistent"],
        "stale_data_count": snapshot["stale_data_count"],
        "stale_data_symbols": snapshot["stale_data_symbols"],
        "date_distribution": snapshot["date_distribution"],
        "downloaded_at": snapshot["downloaded_at"],
        "batch_size": batch_size,
    }
    return df, stats
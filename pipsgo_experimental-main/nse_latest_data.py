from __future__ import annotations

import io
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

NSE_BHAVCOPY_URLS = (
    "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv",
    "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv",
)
NSE_HOME = "https://www.nseindia.com/"
NSE_MARKET_STATUS_URL = "https://www.nseindia.com/api/marketStatus"
IST = ZoneInfo("Asia/Kolkata")
EQUITY_OPEN_TIME = (9, 15)
EQUITY_CLOSE_TIME = (15, 30)
EQUITY_SERIES = {"EQ", "BE"}
NSE_OPEN_STATUSES = {"open", "pre-open", "pre open"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0 Safari/537.36",
    "Accept": "text/csv,application/octet-stream,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": NSE_HOME,
    "Connection": "keep-alive",
}


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(NSE_HOME, timeout=8)
    except Exception:
        pass
    return session


def _read_bhavcopy(content: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(content))
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    required = {"SYMBOL", "SERIES", "DATE1", "CLOSE_PRICE"}
    if not required.issubset(df.columns):
        raise ValueError(f"NSE bhavcopy missing columns: {sorted(required - set(df.columns))}")
    return df


def _fetch_nse_market_status() -> dict:
    session = _make_session()
    response = session.get(NSE_MARKET_STATUS_URL, timeout=12)
    response.raise_for_status()
    payload = response.json()
    for state in payload.get("marketState", []):
        if str(state.get("market", "")).strip().lower() == "capital market":
            return state
    raise RuntimeError("NSE capital-market status was not returned")


def eod_scan_market_open() -> bool:
    state = _fetch_nse_market_status()
    status = str(state.get("marketStatus", "")).strip().lower()
    return status in NSE_OPEN_STATUSES


def _eod_source_mode() -> str:
    now = datetime.now(IST)
    state = _fetch_nse_market_status()
    status = str(state.get("marketStatus", "")).strip().lower()
    if status in NSE_OPEN_STATUSES:
        raise RuntimeError("EOD Scan is unavailable while the NSE Capital Market session is running.")
    if (now.hour, now.minute) < EQUITY_OPEN_TIME:
        return "previous"
    trade_date = pd.to_datetime(str(state.get("tradeDate", "")).strip(), errors="coerce")
    if pd.notna(trade_date) and trade_date.date() == now.date():
        return "today"
    return "previous"


def _fetch_nse_bhavcopy(
    max_lookback_days: int = 5,
    require_today: bool = False,
    equity_only: bool = True,
) -> tuple[str, pd.DataFrame]:
    now = datetime.now(IST)
    today = now.date()
    session = _make_session()
    last_error = None
    end_offset = 0 if require_today else max_lookback_days
    for offset in range(0, end_offset + 1):
        day = today - timedelta(days=offset)
        date_str = day.strftime("%d%m%Y")
        for template in NSE_BHAVCOPY_URLS:
            try:
                response = session.get(template.format(date=date_str), timeout=12)
                response.raise_for_status()
                if not response.content or response.content.lstrip().startswith(b"<"):
                    raise ValueError("NSE returned non-CSV content")
                df = _read_bhavcopy(response.content)
                df["SERIES"] = df["SERIES"].astype(str).str.strip().str.upper()
                if equity_only:
                    df = df[df["SERIES"].isin(EQUITY_SERIES)].copy()
                df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip().str.upper()
                df["CLOSE_PRICE"] = pd.to_numeric(df["CLOSE_PRICE"], errors="coerce")
                df = df.dropna(subset=["SYMBOL", "CLOSE_PRICE"])
                df = df[df["CLOSE_PRICE"] > 0].drop_duplicates("SYMBOL", keep="last")
                if not df.empty:
                    actual_date = pd.to_datetime(df["DATE1"].iloc[0], errors="coerce")
                    if pd.notna(actual_date):
                        actual_day = actual_date.date()
                        if require_today and actual_day != today:
                            raise ValueError(f"NSE returned bhavcopy dated {actual_day}, expected {today}")
                        return actual_day.isoformat(), df
            except Exception as exc:
                last_error = exc
    if require_today:
        raise RuntimeError(f"Today's NSE EOD bhavcopy is not available yet: {last_error}")
    raise RuntimeError(f"Unable to retrieve a recent NSE bhavcopy: {last_error}")


@st.cache_data(show_spinner=False, persist="disk", max_entries=20)
def _fetch_latest_nse_close_cached(
    max_lookback_days: int,
    require_today: bool,
    cache_day: str,
) -> tuple[str, dict[str, float]]:
    actual_date, df = _fetch_nse_bhavcopy(
        max_lookback_days=max_lookback_days,
        require_today=require_today,
        equity_only=True,
    )
    return actual_date, dict(zip(df["SYMBOL"], df["CLOSE_PRICE"].astype(float)))


def fetch_latest_nse_close(max_lookback_days: int = 5, require_today: bool = False) -> tuple[str, dict[str, float]]:
    cache_day = datetime.now(IST).date().isoformat()
    return _fetch_latest_nse_close_cached(max_lookback_days, require_today, cache_day)


def _download_raw_recent(symbols: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for start in range(0, len(symbols), 100):
        group = symbols[start:start + 100]
        try:
            raw = yf.download(
                tickers=[f"{s}.NS" for s in group], period="10d", interval="1d",
                auto_adjust=False, progress=False, group_by="ticker", threads=True,
            )
            if raw is None or raw.empty:
                continue
            level0 = set(raw.columns.get_level_values(0)) if isinstance(raw.columns, pd.MultiIndex) else set()
            level1 = set(raw.columns.get_level_values(1)) if isinstance(raw.columns, pd.MultiIndex) else set()
            for symbol in group:
                ticker = f"{symbol}.NS"
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        if ticker in level0:
                            x = raw[ticker].copy()
                        elif ticker in level1:
                            x = raw.xs(ticker, axis=1, level=1).copy()
                        else:
                            continue
                    else:
                        if len(group) != 1 or "Close" not in raw.columns:
                            continue
                        x = raw.copy()
                    if "Close" not in x.columns:
                        continue
                    x.index = pd.to_datetime(x.index, errors="coerce").tz_localize(None)
                    x = x[~x.index.isna()].sort_index()
                    x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
                    x = x.dropna(subset=["Close"])
                    if not x.empty:
                        result[symbol] = x
                except Exception:
                    continue
        except Exception:
            continue
    return result


def _download_yahoo_2y(symbols: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for start in range(0, len(symbols), 100):
        group = symbols[start:start + 100]
        try:
            raw = yf.download(
                tickers=[f"{s}.NS" for s in group], period="2y", interval="1d",
                auto_adjust=True, progress=False, group_by="ticker", threads=True,
            )
            if raw is None or raw.empty:
                continue
            level0 = set(raw.columns.get_level_values(0)) if isinstance(raw.columns, pd.MultiIndex) else set()
            level1 = set(raw.columns.get_level_values(1)) if isinstance(raw.columns, pd.MultiIndex) else set()
            for symbol in group:
                ticker = f"{symbol}.NS"
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        if ticker in level0:
                            x = raw[ticker].copy()
                        elif ticker in level1:
                            x = raw.xs(ticker, axis=1, level=1).copy()
                        else:
                            continue
                    else:
                        if len(group) != 1 or "Close" not in raw.columns:
                            continue
                        x = raw.copy()
                    if "Close" not in x.columns:
                        continue
                    x.index = pd.to_datetime(x.index, errors="coerce").tz_localize(None)
                    x = x[~x.index.isna()].sort_index()
                    x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
                    x = x.dropna(subset=["Close"])
                    if not x.empty:
                        result[symbol] = x
                except Exception:
                    continue
        except Exception:
            continue
    return result


def source_check(snapshot: dict, symbols: list[str]) -> pd.DataFrame:
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    recent = _download_raw_recent(symbols)
    data = snapshot.get("data", {}) if isinstance(snapshot, dict) else {}
    fallback_2y = _download_yahoo_2y(symbols) if not data else {}
    try:
        nse_date, nse_rows = _fetch_nse_bhavcopy(require_today=False, equity_only=False)
        nse_rows = nse_rows[nse_rows["SYMBOL"].isin(symbols)].copy()
        nse_closes = dict(zip(nse_rows["SYMBOL"], nse_rows["CLOSE_PRICE"].astype(float)))
        if "TTL_TRD_QTY" in nse_rows.columns:
            nse_rows["TTL_TRD_QTY"] = pd.to_numeric(nse_rows["TTL_TRD_QTY"], errors="coerce")
        nse_lookup = {symbol: row for symbol, row in nse_rows.set_index("SYMBOL").iterrows()}
        nse_error = ""
    except Exception as exc:
        nse_date, nse_closes, nse_lookup, nse_error = "—", {}, {}, str(exc)

    rows = []
    for symbol in symbols:
        frame = data.get(symbol) or fallback_2y.get(symbol)
        yahoo_2y_date, yahoo_2y_close = "—", None
        if frame is not None and not frame.empty and "Close" in frame.columns:
            x = frame.copy()
            x.index = pd.to_datetime(x.index, errors="coerce").tz_localize(None)
            x["Close"] = pd.to_numeric(x["Close"], errors="coerce")
            x = x.dropna(subset=["Close"]).sort_index()
            if not x.empty:
                yahoo_2y_date = x.index[-1].date().isoformat()
                yahoo_2y_close = float(x["Close"].iloc[-1])
        yahoo_10d_date, yahoo_10d_close = "—", None
        recent_frame = recent.get(symbol)
        if recent_frame is not None and not recent_frame.empty:
            y = recent_frame.dropna(subset=["Close"]).sort_index()
            if not y.empty:
                yahoo_10d_date = y.index[-1].date().isoformat()
                yahoo_10d_close = float(y["Close"].iloc[-1])
        nse_row = nse_lookup.get(symbol)
        rows.append({
            "Symbol": symbol,
            "Yahoo 2Y Date": yahoo_2y_date,
            "Yahoo 2Y Close": yahoo_2y_close,
            "Yahoo 10D Date": yahoo_10d_date,
            "Yahoo 10D Close": yahoo_10d_close,
            "NSE Date": nse_date,
            "NSE Series": nse_row.get("SERIES") if nse_row is not None else None,
            "NSE Prev Close": nse_row.get("PREV_CLOSE") if nse_row is not None else None,
            "NSE Open": nse_row.get("OPEN_PRICE") if nse_row is not None else None,
            "NSE Close": nse_closes.get(symbol),
            "NSE Volume": nse_row.get("TTL_TRD_QTY") if nse_row is not None else None,
            "NSE Row": "Present" if nse_row is not None else "Not Present",
            "NSE Error": nse_error,
        })
    return pd.DataFrame(rows)


def _refresh_snapshot_diagnostics(snapshot: dict) -> None:
    data = snapshot.get("data", {})
    latest_by_symbol = {}
    for symbol, frame in data.items():
        if frame is None or frame.empty:
            continue
        try:
            latest_by_symbol[symbol] = pd.Timestamp(frame.index[-1]).date().isoformat()
        except Exception:
            continue
    dates = list(latest_by_symbol.values())
    if dates:
        counts = Counter(dates)
        min_date, max_date = min(dates), max(dates)
        stale_symbols = sorted(symbol for symbol, date in latest_by_symbol.items() if date < max_date)
        snapshot["data_date"] = max_date
        snapshot["min_data_date"] = min_date
        snapshot["max_data_date"] = max_date
        snapshot["date_consistent"] = min_date == max_date
        snapshot["stale_data_count"] = len(stale_symbols)
        snapshot["stale_data_symbols"] = stale_symbols
        snapshot["date_distribution"] = dict(sorted(counts.items(), key=lambda item: item[0], reverse=True))
    else:
        snapshot["data_date"] = "Unknown"
        snapshot["min_data_date"] = "Unknown"
        snapshot["max_data_date"] = "Unknown"
        snapshot["date_consistent"] = False
        snapshot["stale_data_count"] = 0
        snapshot["stale_data_symbols"] = []
        snapshot["date_distribution"] = {}

    universe = int(snapshot.get("universe", len(data)))
    usable_symbols = []
    for symbol, frame in data.items():
        if frame is None or frame.empty or "Close" not in frame.columns:
            continue
        if len(frame["Close"].dropna()) > 252:
            usable_symbols.append(symbol)
    stale_set = set(snapshot.get("stale_data_symbols", []))
    usable_symbols = [symbol for symbol in usable_symbols if symbol not in stale_set]
    missing = sorted(set(snapshot.get("missing", [])))
    short_history = sorted((set(data) - set(usable_symbols)) | stale_set)
    snapshot["downloaded"] = len(data)
    snapshot["missing"] = missing
    snapshot["missing_count"] = len(missing)
    snapshot["short_history"] = short_history
    snapshot["short_history_count"] = len(short_history)
    snapshot["usable"] = len(usable_symbols)
    snapshot["usable_coverage"] = (len(usable_symbols) / universe * 100) if universe else 0


def patch_snapshot(snapshot: dict, progress_callback=None) -> dict:
    data = snapshot.get("data", {})
    if not data or str(snapshot.get("mode", "eod")).lower() != "eod":
        return snapshot

    mode = _eod_source_mode()
    if snapshot.get("nse_source_mode") == mode and snapshot.get("nse_data_date"):
        if progress_callback:
            progress_callback(1, 1, f"NSE latest close already applied · {snapshot['nse_data_date']}")
        return snapshot

    if progress_callback:
        progress_callback(0, 1, "Loading latest NSE bhavcopy")
    if mode == "today":
        nse_date, closes = fetch_latest_nse_close(require_today=True)
    else:
        nse_date, closes = fetch_latest_nse_close(max_lookback_days=10, require_today=False)

    raw_recent = _download_raw_recent(list(data.keys()))
    target = pd.Timestamp(nse_date)
    updated = 0
    factor_count = 0
    for symbol, frame in data.items():
        nse_close = closes.get(symbol)
        if nse_close is None or frame is None or frame.empty:
            continue
        raw = raw_recent.get(symbol)
        adjusted_factor = None
        if raw is not None and not raw.empty:
            common = frame.index.intersection(raw.index)
            common = common[common <= target]
            if len(common):
                ref_date = common[-1]
                adjusted_close = pd.to_numeric(frame.loc[ref_date, "Close"], errors="coerce")
                raw_close = pd.to_numeric(raw.loc[ref_date, "Close"], errors="coerce")
                if pd.notna(adjusted_close) and pd.notna(raw_close) and float(raw_close) > 0:
                    adjusted_factor = float(adjusted_close) / float(raw_close)
                    factor_count += 1
        scaled_close = float(nse_close) * adjusted_factor if adjusted_factor is not None else float(nse_close)
        x = frame.copy()
        if target in x.index:
            x.loc[target, "Close"] = scaled_close
        else:
            row = {column: float("nan") for column in x.columns}
            row["Close"] = scaled_close
            x = pd.concat([x, pd.DataFrame([row], index=[target])])
        x.index = pd.to_datetime(x.index, errors="coerce").tz_localize(None)
        x = x[~x.index.isna()].sort_index()
        x = x[~x.index.duplicated(keep="last")]
        data[symbol] = x
        updated += 1

    snapshot["data"] = data
    snapshot["nse_data_date"] = nse_date
    snapshot["nse_source_mode"] = mode
    snapshot["nse_close_symbols"] = updated
    snapshot["nse_adjustment_factors"] = factor_count
    snapshot["nse_source"] = "NSE official CM bhavcopy"
    _refresh_snapshot_diagnostics(snapshot)
    if progress_callback:
        progress_callback(1, 1, f"NSE latest close applied · {updated:,} symbols")
    return snapshot


@st.cache_data(show_spinner=False, persist="disk", max_entries=200)
def _cached_engine_batch(
    symbols_tuple: tuple[str, ...],
    period: str,
    threads: bool,
    cache_day: str,
    _download_fn,
) -> dict[str, pd.DataFrame]:
    result = _download_fn(list(symbols_tuple), retries=3, threads=threads, period=period)
    if len(result) < len(symbols_tuple):
        raise RuntimeError("Incomplete batch; do not cache partial market data")
    return result


def install_nse_latest_close(engine_module) -> None:
    if getattr(engine_module, "_nse_latest_close_installed", False):
        return

    original_download_universe = engine_module._download_universe
    original_download_batch = engine_module._download_batch
    original_clear_cache = engine_module.clear_stock_data_cache

    def cached_download_batch(symbols, retries=3, threads=True, period="2y"):
        cache_day = datetime.now(IST).date().isoformat()
        try:
            return _cached_engine_batch(
                tuple(symbols), period, threads, cache_day, original_download_batch
            )
        except RuntimeError:
            return original_download_batch(symbols, retries=retries, threads=threads, period=period)

    def wrapped_download_universe(*args, **kwargs):
        engine_module._download_batch = cached_download_batch
        try:
            snapshot = original_download_universe(*args, **kwargs)
        finally:
            engine_module._download_batch = original_download_batch
        return patch_snapshot(snapshot, kwargs.get("progress_callback"))

    def clear_all_stock_data_cache():
        original_clear_cache()
        _cached_engine_batch.clear()
        _fetch_latest_nse_close_cached.clear()

    engine_module._download_universe = wrapped_download_universe
    engine_module.clear_stock_data_cache = clear_all_stock_data_cache
    engine_module._nse_latest_close_installed = True

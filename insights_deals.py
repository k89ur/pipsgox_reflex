from datetime import date, timedelta
from io import BytesIO

import cloudscraper
import pandas as pd


NSE_BASE = "https://www.nseindia.com"
NSE_ARCHIVES_BASE = "https://nsearchives.nseindia.com"
NSE_REPORT_URL = f"{NSE_BASE}/report-detail/display-bulk-and-block-deals"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": NSE_REPORT_URL,
    "Origin": NSE_BASE,
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}

REPORT_TYPES = {
    "block": ("block-deals", "block_deals"),
    "short_selling": ("short-selling", "short_selling"),
}


def _session():
    session = cloudscraper.create_scraper(browser="chrome")
    session.headers.update(NSE_HEADERS)
    session.get(NSE_BASE, timeout=20)
    try:
        session.get(NSE_REPORT_URL, timeout=20)
    except Exception:
        pass
    return session


def _rows(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "records", "rows", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _column_key(column):
    return "".join(ch for ch in str(column).lower() if ch.isalnum())


def _normalise_columns(frame):
    if frame.empty:
        return frame

    result = frame.copy()
    result.columns = [str(c).strip() for c in result.columns]
    renamed = {}

    for column in result.columns:
        key = _column_key(column)
        if key in {"date", "tradedate", "ssdate", "bddate", "blkdate"} or key.endswith("date"):
            renamed[column] = "date"
        elif key in {"symbol", "sssymbol", "bdsymbol", "blksymbol"} or key.endswith("symbol"):
            renamed[column] = "symbol"
        elif key in {"securityname", "ssname", "bdname", "blkname", "scripname"}:
            renamed[column] = "securityName"
        elif key in {"clientname", "client", "ssclientname", "bdclientname", "blkclientname"}:
            renamed[column] = "clientName"
        elif key in {"buysell", "buyorsell", "buyorsellindicator", "transaction"}:
            renamed[column] = "buySell"
        elif key in {"quantity", "qty", "ssqty", "bdqty", "blkqty", "quantitytraded"}:
            renamed[column] = "qty"
        elif key in {"tradeprice", "tradepriceweightedaverageprice", "weightedaverageprice", "price", "watp"}:
            renamed[column] = "watp"
        elif key == "remarks":
            renamed[column] = "remarks"

    result = result.rename(columns=renamed)
    if result.columns.duplicated().any():
        result = result.loc[:, ~result.columns.duplicated(keep="first")]
    return result


def _filter_symbol(frame, symbol):
    if frame.empty or "symbol" not in frame.columns:
        return frame
    wanted = str(symbol).strip().upper()
    return frame[
        frame["symbol"].astype(str).str.strip().str.upper() == wanted
    ].copy()


def _request_historical(session, report, option_type, from_date, to_date):
    response = session.get(
        f"{NSE_BASE}/api/historical/{report}",
        params={
            "from": from_date,
            "to": to_date,
            "optionType": option_type,
        },
        headers={"Referer": NSE_REPORT_URL, "X-Requested-With": "XMLHttpRequest"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _historical(session, report, option_type, from_date, to_date):
    payload = _request_historical(session, report, option_type, from_date, to_date)
    return _normalise_columns(pd.DataFrame(_rows(payload)))


def _bulk_archive(start_date, end_date, symbol):
    """Fetch NSE's official one-file historical bulk-deals archive."""
    filename = (
        f"Bulk-Deals-{start_date:%d-%m-%Y}-to-{end_date:%d-%m-%Y}.csv"
    )
    urls = (
        f"{NSE_ARCHIVES_BASE}/content/equities/{filename}",
        f"https://archives.nseindia.com/content/equities/{filename}",
    )

    last_error = None
    for url in urls:
        try:
            session = _session()
            response = session.get(url, timeout=30)
            response.raise_for_status()
            content = response.content
            if not content or content.lstrip().startswith(b"<"):
                raise ValueError("NSE archive returned HTML instead of CSV")
            frame = pd.read_csv(BytesIO(content))
            return _filter_symbol(_normalise_columns(frame), symbol), None
        except Exception as exc:
            last_error = exc

    return pd.DataFrame(), f"bulk archive: {last_error}"


def fetch_nse_historical_deals(symbol, days=365):
    """Fetch NSE historical bulk, block and short-selling records for one symbol."""
    end = date.today()
    start = end - timedelta(days=min(max(int(days), 1), 365) - 1)
    from_date = start.strftime("%d-%m-%Y")
    to_date = end.strftime("%d-%m-%Y")

    empty = {
        "bulk": pd.DataFrame(),
        "block": pd.DataFrame(),
        "short_selling": pd.DataFrame(),
        "from_date": from_date,
        "to_date": to_date,
        "source": "NSE historical deal reports",
        "available": False,
        "failed_reports": [],
    }

    try:
        session = _session()
        frames = {}
        failed_reports = []
        successful_reports = []

        # Bulk deals have a dedicated official NSE historical-range archive.
        bulk_frame, bulk_error = _bulk_archive(start, end, symbol)
        frames["bulk"] = bulk_frame
        if not bulk_frame.empty:
            successful_reports.append("bulk")
        elif bulk_error:
            failed_reports.append(bulk_error)

        # Block and short-selling remain on NSE's historical report API.
        # Keep these as single range requests; never fall back to hundreds of
        # per-day downloads that make the Insights page excessively slow.
        for key, (endpoint, option_type) in REPORT_TYPES.items():
            try:
                frame = _historical(session, endpoint, option_type, from_date, to_date)
                frames[key] = _filter_symbol(frame, symbol)
                if not frames[key].empty:
                    successful_reports.append(key)
            except Exception as exc:
                frames[key] = pd.DataFrame()
                failed_reports.append(f"{key}: {exc}")

        result = {
            **empty,
            **frames,
            "available": bool(successful_reports),
            "failed_reports": failed_reports,
        }
        if not successful_reports:
            result["error"] = "NSE historical deal data could not be loaded."
        elif failed_reports:
            result["warning"] = "Some NSE deal sources failed; successful records are still shown."
        return result
    except Exception as exc:
        return {**empty, "error": str(exc)}

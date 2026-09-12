import json
import time
from datetime import datetime, timedelta, timezone

import streamlit as st
from streamlit_cookies_controller import CookieController

WATCHLIST_KEY = "watchlist_symbols"
WATCHLIST_COOKIE = "pipsgo_watchlist_v1"
WATCHLIST_DAYS = 15
CONTROLLER_KEY = "watchlist_cookie_controller"
LOADED_KEY = "watchlist_cookie_loaded"


def _controller():
    controller = st.session_state.get(CONTROLLER_KEY)
    if controller is None:
        controller = CookieController(key="pipsgo_watchlist_cookie")
        st.session_state[CONTROLLER_KEY] = controller
    return controller


def _now():
    return datetime.now(timezone.utc)


def _parse_added_at(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _normalise_records(records):
    now = _now()
    cleaned = []
    seen = set()
    for record in records or []:
        if isinstance(record, str):
            symbol = record.strip().upper()
            added_at = now
        elif isinstance(record, dict):
            symbol = str(record.get("symbol", "")).strip().upper()
            added_at = _parse_added_at(record.get("added_at")) or now
        else:
            continue
        if not symbol or symbol in seen:
            continue
        if now - added_at < timedelta(days=WATCHLIST_DAYS):
            cleaned.append({"symbol": symbol, "added_at": added_at.isoformat()})
            seen.add(symbol)
    return cleaned


def _write_cookie(records):
    controller = _controller()
    if not records:
        controller.remove(WATCHLIST_COOKIE)
        return

    latest_expiry = max(
        datetime.fromisoformat(record["added_at"]).astimezone(timezone.utc)
        + timedelta(days=WATCHLIST_DAYS)
        for record in records
    )
    controller.set(
        WATCHLIST_COOKIE,
        {
            "value": json.dumps(records, separators=(",", ":")),
            "expiry_date": latest_expiry.isoformat(),
        },
    )


def _save(records):
    records = _normalise_records(records)
    st.session_state[WATCHLIST_KEY] = records
    _write_cookie(records)
    return records


def _read_cookie():
    controller = _controller()
    raw = controller.get(WATCHLIST_COOKIE)
    if raw is None:
        controller.getAll()
        time.sleep(1.0)
        raw = controller.get(WATCHLIST_COOKIE)

    if isinstance(raw, dict):
        raw = raw.get("value")
    if not raw:
        return []
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []


def _load():
    if st.session_state.get(LOADED_KEY):
        return _normalise_records(st.session_state.get(WATCHLIST_KEY, []))

    records = _read_cookie()
    migrated = False
    if not records and st.session_state.get(WATCHLIST_KEY):
        records = st.session_state[WATCHLIST_KEY]
        migrated = True

    original = records
    records = _normalise_records(records)
    st.session_state[WATCHLIST_KEY] = records
    st.session_state[LOADED_KEY] = True

    if migrated or records != original:
        _save(records)
    return records


def get_watchlist_records():
    return list(_load())


def get_watchlist():
    return [record["symbol"] for record in _load()]


def is_watched(symbol):
    symbol = str(symbol).strip().upper()
    return symbol in {record["symbol"] for record in _load()}


def add_stock(symbol):
    symbol = str(symbol).strip().upper()
    records = _load()
    if symbol and symbol not in {record["symbol"] for record in records}:
        records.append({"symbol": symbol, "added_at": _now().isoformat()})
        _save(records)
    return symbol


def remove_stock(symbol):
    symbol = str(symbol).strip().upper()
    records = [record for record in _load() if record["symbol"] != symbol]
    _save(records)
    return symbol


def toggle_stock(symbol):
    if is_watched(symbol):
        return remove_stock(symbol), False
    return add_stock(symbol), True

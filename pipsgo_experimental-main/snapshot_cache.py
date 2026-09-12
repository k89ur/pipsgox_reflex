from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

IST = ZoneInfo("Asia/Kolkata")


@st.cache_data(show_spinner=False, persist="disk", max_entries=200)
def _cached_stock_batch(
    symbols_tuple: tuple[str, ...],
    retries: int,
    threads: bool,
    period: str,
    cache_day: str,
    _download_fn,
) -> dict:
    """Persist one complete Yahoo batch independently of the browser session."""
    result = _download_fn(
        list(symbols_tuple),
        retries=retries,
        threads=threads,
        period=period,
    )
    if len(result) < len(symbols_tuple):
        raise RuntimeError("Incomplete batch; do not cache partial market data")
    return result


def install(engine_module) -> None:
    """Persist stock market-data batches while keeping the engine progress callbacks."""
    if getattr(engine_module, "_persistent_snapshot_installed", False):
        return

    original_download_batch = engine_module._download_batch
    original_download_universe = engine_module._download_universe
    original_clear_cache = engine_module.clear_stock_data_cache

    def cached_download_batch(symbols, retries=3, threads=True, period="2y"):
        symbols = list(symbols)
        if not symbols:
            return {}
        cache_day = datetime.now(IST).date().isoformat()
        try:
            return _cached_stock_batch(
                tuple(symbols),
                int(retries),
                bool(threads),
                str(period),
                cache_day,
                original_download_batch,
            )
        except RuntimeError:
            # Never persist partial batches; let the engine's recovery logic handle them.
            return original_download_batch(
                symbols,
                retries=retries,
                threads=threads,
                period=period,
            )

    def wrapped_download_universe(
        symbols,
        batch_size=100,
        snapshot_mode="eod",
        force_refresh=False,
        progress_callback=None,
    ):
        if force_refresh:
            _cached_stock_batch.clear()
        # The original engine owns snapshot orchestration and progress reporting.
        # Its calls to _download_batch now transparently use the persistent batch cache.
        return original_download_universe(
            symbols,
            batch_size=batch_size,
            snapshot_mode=snapshot_mode,
            force_refresh=force_refresh,
            progress_callback=progress_callback,
        )

    def clear_all_stock_data_cache():
        original_clear_cache()
        _cached_stock_batch.clear()

    engine_module._download_batch = cached_download_batch
    engine_module._download_universe = wrapped_download_universe
    engine_module.clear_stock_data_cache = clear_all_stock_data_cache
    engine_module._persistent_snapshot_installed = True

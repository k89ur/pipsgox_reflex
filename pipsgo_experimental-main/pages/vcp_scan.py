import streamlit as st
from nse_latest_data import eod_scan_market_open
from snapshot_cache import install as install_persistent_snapshot
import vcp_engine

install_persistent_snapshot(vcp_engine.rs_engine)
clear_market_data_cache = vcp_engine.rs_engine.clear_stock_data_cache

if "vcp_result" not in st.session_state:
    st.session_state.vcp_result = None
if "vcp_stats" not in st.session_state:
    st.session_state.vcp_stats = None
if "vcp_full_table" not in st.session_state:
    st.session_state.vcp_full_table = False
if "vcp_columns" not in st.session_state:
    st.session_state.vcp_columns = None

COLUMNS = [
    "Symbol", "Index", "Industry", "LTP", "52W High", "From 52W High %",
    "52W Low", "From 52W Low %", "50DMA", "Price vs 50DMA %", "150DMA", "200DMA",
    "TradingView",
]

BOOL_COLUMNS = []


def column_config():
    return {
        "Symbol": st.column_config.TextColumn("SYMBOL"),
        "Index": st.column_config.TextColumn("INDEX"),
        "Industry": st.column_config.TextColumn("INDUSTRY"),
        "LTP": st.column_config.NumberColumn("LTP", format="₹%.2f"),
        "52W High": st.column_config.NumberColumn("52W HIGH", format="₹%.2f"),
        "From 52W High %": st.column_config.NumberColumn("FROM 52W HIGH", format="%.1f%%"),
        "52W Low": st.column_config.NumberColumn("52W LOW", format="₹%.2f"),
        "From 52W Low %": st.column_config.NumberColumn("FROM 52W LOW", format="%.1f%%"),
        "50DMA": st.column_config.NumberColumn("50 DMA", format="₹%.2f"),
        "Price vs 50DMA %": st.column_config.NumberColumn("VS 50 DMA", format="%.1f%%"),
        "150DMA": st.column_config.NumberColumn("150 DMA", format="₹%.2f"),
        "200DMA": st.column_config.NumberColumn("200 DMA", format="₹%.2f"),
        "TradingView": st.column_config.LinkColumn("CHART", display_text="Open ↗", width="small"),
    }


def prepare_table(data):
    table = data.copy()
    for col in BOOL_COLUMNS:
        if col in table.columns:
            table[col] = table[col].map({True: "YES", False: "NO"}).fillna("—")
    return table


def visible_vcp_columns():
    saved = st.session_state.get("vcp_columns")
    if saved:
        valid = [col for col in saved if col in COLUMNS]
        return valid or COLUMNS.copy()
    return COLUMNS.copy()


@st.dialog("Reset Market Data")
def reset_market_data_dialog():
    st.warning("Downloaded market data will be cleared and must be downloaded again.")
    st.write("Are you sure you want to reset the VCP market-data cache?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Confirm reset", type="primary", use_container_width=True, key="confirm_vcp_reset"):
            clear_market_data_cache()
            st.session_state.vcp_result = None
            st.session_state.vcp_stats = None
            st.session_state.vcp_full_table = False
            st.session_state.vcp_columns = None
            st.rerun()
    with c2:
        if st.button("Cancel", use_container_width=True, key="cancel_vcp_reset"):
            st.rerun()


@st.dialog("VCP Table Columns")
def vcp_column_selector(all_columns, saved_columns):
    st.caption("Select the columns you want to display in the VCP results table.")
    for col in all_columns:
        st.checkbox(col, value=(col in saved_columns), key=f"vcp_col_select_{col}")
    st.divider()
    if st.button("Apply", type="primary", use_container_width=True, key="apply_vcp_columns"):
        st.session_state.vcp_columns = [
            col for col in all_columns if st.session_state.get(f"vcp_col_select_{col}", False)
        ] or ["Symbol"]
        st.rerun()


st.markdown('<div class="page-brand"><span>PIPS</span>GOX</div>', unsafe_allow_html=True)
st.markdown('<div class="page-head"><div class="page-title">VCP Type Scan</div><div class="page-sub">Trend · 52W position · 50DMA position</div></div>', unsafe_allow_html=True)

if st.session_state.vcp_full_table:
    df = st.session_state.vcp_result
    if df is None or df.empty:
        st.info("Run a VCP scan first to open the full table.")
    else:
        full = prepare_table(df[[c for c in visible_vcp_columns() if c in df.columns]])
        full.insert(0, "S.No", range(1, len(full) + 1))
        _, close = st.columns([20, 1], gap="small")
        with close:
            if st.button("", icon=":material/fullscreen_exit:", type="tertiary", width=30, key="vcp_minimize", help="Return to scanner"):
                st.session_state.vcp_full_table = False
                st.rerun()
        st.dataframe(
            full,
            use_container_width=True,
            hide_index=True,
            height=min(900, 95 + max(len(full), 1) * 36),
            column_config=column_config(),
        )
    st.stop()

main, side = st.columns([4.7, 1.35], gap="large")
with side:
    with st.container(border=True):
        st.markdown('<div class="right-title">Scanner status</div>', unsafe_allow_html=True)
        progress_slot = st.empty()
        status_slot = st.empty()

with main:
    with st.container(border=True):
        st.markdown('<div class="section-title" style="margin-top:.05rem">VCP settings</div>', unsafe_allow_html=True)
        a, b = st.columns(2, gap="small")
        with a:
            trend_filter = st.checkbox("Trend filter", True, key="vcp_trend")
            st.caption("Price ≥ 50 / 150 / 200 DMA + all three MAs rising over the last 20 trading days.")
        with b:
            dma_position_filter = st.checkbox("50DMA position", True, key="vcp_dma_position")
            dma_position_pct = st.slider("Within 50DMA ± %", 0.0, 30.0, 15.0, step=1.0, key="vcp_dma_pct")

        st.markdown('<div style="height:.15rem"></div>', unsafe_allow_html=True)
        c, d = st.columns(2, gap="small")
        with c:
            use_52w_high = st.checkbox("52W High filter", True, key="vcp_52w_high_enabled")
            near_high = st.slider("Within 52W High %", 0.0, 10.0, 5.0, step=0.5, key="vcp_near_high")
        with d:
            use_52w_low = st.checkbox("52W Low filter", False, key="vcp_52w_low_enabled")
            prior_low_pct = st.slider("Minimum advance from 52W Low %", 30.0, 300.0, 70.0, step=5.0, key="vcp_52w_low_pct")

        st.markdown('<div style="height:.15rem"></div>', unsafe_allow_html=True)
        i, j, reset = st.columns([1.45, 1.45, 1.55], gap="small")
        with i:
            live = st.button("▶ Live Market Scan", type="primary", use_container_width=True, key="vcp_live")
        with j:
            eod = st.button("▶ After Market Scan", use_container_width=True, key="vcp_eod")
        with reset:
            if st.button("↻ Reset Market Data", use_container_width=True, key="vcp_reset"):
                reset_market_data_dialog()
        status = st.empty()

if live or eod:
    mode = "intraday" if live else "eod"
    if mode == "eod":
        try:
            if eod_scan_market_open():
                status.error("After Market Scan is unavailable while the NSE Capital Market session is running.")
                st.stop()
        except Exception as exc:
            status.error(f"Unable to verify NSE Capital Market session status. ({exc})")
            st.stop()
    progress_slot.progress(0, text="Starting VCP scan…")
    try:
        def update(done, total, label):
            progress_slot.progress(int(done / total * 100) if total else 0, text=f"{label} · {done:,}/{total:,}")

        with st.spinner("Running VCP scan…"):
            result, stats = vcp_engine.run_scan(
                trend_filter=trend_filter,
                use_52w_high=use_52w_high,
                near_high_pct=near_high,
                use_52w_low=use_52w_low,
                prior_low_pct=prior_low_pct,
                dma_position_filter=dma_position_filter,
                dma_position_pct=dma_position_pct,
                batch_size=vcp_engine.DEFAULT_BATCH_SIZE,
                snapshot_mode=mode,
                progress_callback=update,
            )
        st.session_state.vcp_result = result
        st.session_state.vcp_stats = stats
        progress_slot.empty()
        status.success(f"VCP scan complete · {len(result):,} matches")
    except Exception as exc:
        progress_slot.empty()
        status.error(f"VCP scan failed: {exc}")

with main:
    df = st.session_state.vcp_result
    stats = st.session_state.vcp_stats
    if stats:
        status_slot.markdown(
            f"<div class='rstat'><div class='rstat-label'>Matches</div><div class='rstat-value'>{stats.get('matches',0):,}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Universe</div><div class='rstat-value'>{stats.get('universe',0):,}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Usable</div><div class='rstat-value'>{stats.get('usable',0):,}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Coverage</div><div class='rstat-value'>{stats.get('coverage',0):.1f}%</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Data</div><div class='rstat-value'>{stats.get('data_date','—')}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Snapshot</div><div class='rstat-value'>{str(stats.get('snapshot_mode','—')).upper()}</div></div>",
            unsafe_allow_html=True,
        )
    if df is not None:
        st.markdown(f'<div class="section-title">VCP Results · {len(df):,}</div>', unsafe_allow_html=True)
        if df.empty:
            st.info("No stocks matched the current VCP settings.")
        else:
            selected_columns = visible_vcp_columns()
            spacer, tool1, tool2, tool3 = st.columns([18, 0.45, 0.45, 0.45], gap="small")
            with tool1:
                if st.button("", icon=":material/view_column:", type="tertiary", width=30, key="vcp_columns", help="Select columns"):
                    vcp_column_selector(COLUMNS, selected_columns)
            with tool2:
                csv_data = df[[c for c in selected_columns if c in df.columns]].to_csv(index=False).encode("utf-8")
                st.download_button("", data=csv_data, file_name="vcp_results.csv", mime="text/csv", icon=":material/download:", type="tertiary", width=30, key="vcp_download", help="Download CSV")
            with tool3:
                if st.button("", icon=":material/fullscreen:", type="tertiary", width=30, key="vcp_full", help="Full screen view"):
                    st.session_state.vcp_full_table = True
                    st.rerun()
            view = prepare_table(df[[c for c in selected_columns if c in df.columns]])
            st.dataframe(
                view.head(50),
                use_container_width=True,
                hide_index=True,
                height=min(650, 95 + min(len(view), 15) * 36),
                column_config=column_config(),
            )
            if len(df) > 50:
                st.caption(f"Showing top 50 of {len(df):,} matches. Use Full screen view for the complete table.")

import streamlit as st
import pandas as pd
from index_rs_engine import run_index_scan

if "index_result" not in st.session_state:
    st.session_state.index_result = None
if "index_full_table" not in st.session_state:
    st.session_state.index_full_table = False

@st.dialog("Table columns")
def index_column_selector(all_columns, saved_columns):
    st.caption("Select the columns you want to display.")
    selected = []
    for col in all_columns:
        if st.checkbox(col, value=(col in saved_columns), key=f"index_col_select_{col}"):
            selected.append(col)
    st.divider()
    if st.button("Apply", type="primary", use_container_width=True, key="apply_index_columns"):
        st.session_state.index_columns = selected or ["Rank", "INDEX", "Strength", "RS 1-99"]
        st.rerun()

st.markdown('<div class="page-brand"><span>PIPS</span>GOX</div>', unsafe_allow_html=True)
st.markdown('<div class="page-head"><div class="page-title">NIFTY Relative Strength</div><div class="page-sub">28 industries · IBD-style relative strength · Pine-compatible daily calculation</div></div>', unsafe_allow_html=True)

if st.session_state.index_full_table:
    df = st.session_state.index_result
    if df is None or df.empty:
        st.info("Run an Index RS scan first to open the full table.")
        if st.button("", icon=":material/fullscreen_exit:", type="tertiary", width=30, key="index_full_minimize_empty", help="Return to scanner"):
            st.session_state.index_full_table = False
            st.rerun()
        st.stop()

    full_table = df.copy()
    full_table.insert(0, "S.No", range(1, len(full_table) + 1))
    full_table["TradingView"] = full_table["INDEX"].map(lambda x: f"https://www.tradingview.com/chart/?symbol=NSE%3A{x}")

    def index_style(row):
        styles = [""] * len(row)
        if "RS 1-99" in row.index and pd.notna(row["RS 1-99"]):
            score = float(row["RS 1-99"])
            fg = "#35d07f" if score >= 80 else ("#f3b94b" if score >= 50 else "#ff6673")
            styles[row.index.get_loc("RS 1-99")] = f"color:{fg};font-weight:700;"
        return styles

    top_spacer, minimize = st.columns([20, 1], gap="small")
    with minimize:
        if st.button("", icon=":material/fullscreen_exit:", type="tertiary", width=30, key="index_full_minimize", help="Return to scanner"):
            st.session_state.index_full_table = False
            st.rerun()

    st.dataframe(
        full_table.style.apply(index_style, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(900, 95 + max(len(full_table), 1) * 36),
        column_config={
            "S.No": st.column_config.NumberColumn("S.NO", format="%d", width="small"),
            "Rank": st.column_config.NumberColumn("#", format="%d", width="small"),
            "INDEX": st.column_config.TextColumn("INDEX", width="medium"),
            "RS 1-99": st.column_config.NumberColumn("RS", format="%d", width="small"),
            "Raw RS": st.column_config.NumberColumn("RAW RS", format="%.2f", width="small"),
            "3M %": st.column_config.NumberColumn("3M", format="%.1f%%"),
            "6M %": st.column_config.NumberColumn("6M", format="%.1f%%"),
            "9M %": st.column_config.NumberColumn("9M", format="%.1f%%"),
            "12M %": st.column_config.NumberColumn("12M", format="%.1f%%"),
            "LTP": st.column_config.NumberColumn("LTP", format="₹%.2f"),
            "Bars": st.column_config.NumberColumn("BARS", format="%d", width="small"),
            "First Date": st.column_config.DateColumn("FIRST DATE", format="DD MMM YYYY", width="medium"),
            "Latest Date": st.column_config.DateColumn("LATEST DATE", format="DD MMM YYYY", width="medium"),
            "Status": st.column_config.TextColumn("STATUS", width="small"),
            "TradingView": st.column_config.LinkColumn("CHART", display_text="Open ↗", width="small"),
        },
    )
    st.stop()

# Keep controls/status in the top row. Results render inside the left/main
# column so the large blank area beneath Scan Settings is used immediately.
main, side = st.columns([4.7, 1.35], gap="large")
with side:
    with st.container(border=True):
        st.markdown('<div class="right-title">Scanner status</div>', unsafe_allow_html=True)
        status_slot = st.empty(); stats_slot = st.empty()

with main:
    with st.container(border=True):
        st.markdown('<div class="section-title" style="margin-top:.05rem">Scan settings</div>', unsafe_allow_html=True)
        run_index = st.button("↻  Refresh Index RS", type="primary")

if run_index or st.session_state.index_result is None:
    progress = status_slot.progress(0, text="Connecting to TradingView…")
    try:
        def update(done, total, message):
            pct = min(done / max(total, 1), 1.0)
            progress.progress(pct, text=f"{message} · {done}/{total}")
            stats_slot.markdown(f"<div class='rstat'><div class='rstat-label'>Progress</div><div class='rstat-value'>{pct*100:.0f}%</div></div><div class='rstat'><div class='rstat-label'>Processed</div><div class='rstat-value'>{done}/{total}</div></div>", unsafe_allow_html=True)

        df, stats = run_index_scan(update)
        st.session_state.index_result = df
        st.session_state.index_stats = stats
        progress.progress(1.0, text="Scan complete")
    except Exception as e:
        progress.empty()
        status_slot.error("Scan failed")
        st.error(f"TradingView data refresh failed: {e}")

with main:
    df = st.session_state.index_result
    if df is None:
        status_slot.markdown('<div class="rstat"><div class="rstat-label">Status</div><div class="rstat-value">Waiting</div></div><div class="help">Press Refresh to calculate the index universe.</div>', unsafe_allow_html=True)
        st.markdown('<div class="empty-state"><div class="empty-title">Ready to scan</div><div class="empty-sub">Calculate current relative strength for all supported NIFTY industry indices.</div></div>', unsafe_allow_html=True)
    else:
        stats = st.session_state.get("index_stats", {})
        valid = df[df["Raw RS"].notna()].copy()
        strong = int((valid["RS 1-99"] >= 80).sum())
        weak = int((valid["RS 1-99"] < 50).sum())
        asof = stats.get("benchmark_latest", stats.get("as_of"))
        asof_text = asof.strftime("%d %b %Y") if hasattr(asof, "strftime") else "—"
        unavailable = int(stats.get("unavailable_count", int(df["Latest Date"].isna().sum())))
        stale = int(stats.get("stale_count", 0))
        insufficient = int((df["Latest Date"].notna() & df["Raw RS"].isna()).sum())

        stats_slot.markdown(
            f"<div class='rstat'><div class='rstat-label'>Latest data</div><div class='rstat-value'>{asof_text}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Universe</div><div class='rstat-value'>{stats.get('universe',28)}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Calculated</div><div class='rstat-value'>{stats.get('available',0)}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Stale</div><div class='rstat-value'>{stale}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Insufficient history</div><div class='rstat-value'>{insufficient}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Unavailable</div><div class='rstat-value'>{unavailable}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Strong · 80+</div><div class='rstat-value score-strong'>{strong}</div></div>"
            f"<div class='rstat'><div class='rstat-label'>Weak · &lt;50</div><div class='rstat-value score-weak'>{weak}</div></div>",
            unsafe_allow_html=True,
        )

        top = valid.head(3)
        st.markdown('<div class="section-title">Leaders</div>', unsafe_allow_html=True)
        if len(top):
            cards = []
            for _, row in top.iterrows():
                score = int(row["RS 1-99"])
                cls = "score-strong" if score >= 80 else ("score-mid" if score >= 50 else "score-weak")
                cards.append(
                    f"<div class='leader'><div class='leader-top'><span class='leader-rank'>#{int(row['Rank']):02d}</span><span class='leader-score {cls}'>{score}</span></div><div class='leader-name'>{row['INDEX']}</div><div class='help'>Raw RS {row['Raw RS']:.2f}</div></div>"
                )
            st.markdown('<div class="leader-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)
        search_col, filter_col = st.columns([2.8, 1.7])
        with search_col:
            search = st.text_input("Search", placeholder="Search index…", label_visibility="collapsed", key="index_search")
        with filter_col:
            filter_mode = st.selectbox("Filter", ["All", "Strong · 80+", "Middle · 50–79", "Weak · <50", "Unavailable"], label_visibility="collapsed", key="index_filter")

        view = df.copy()
        if search:
            view = view[view["INDEX"].str.contains(search, case=False, na=False)]
        if filter_mode == "Strong · 80+":
            view = view[view["RS 1-99"] >= 80]
        elif filter_mode == "Middle · 50–79":
            view = view[(view["RS 1-99"] >= 50) & (view["RS 1-99"] < 80)]
        elif filter_mode == "Weak · <50":
            view = view[(view["RS 1-99"] < 50) & view["RS 1-99"].notna()]
        elif filter_mode == "Unavailable":
            view = view[view["RS 1-99"].isna()]

        show = view[["Rank", "INDEX", "RS 1-99", "Raw RS", "3M %", "6M %", "9M %", "12M %", "LTP", "Bars", "First Date", "Latest Date", "Status"]].copy()
        show["Rank"] = show["Rank"].astype(int)
        show.insert(2, "Strength", show["RS 1-99"].map(lambda s: "N/A" if pd.isna(s) else ("Strong" if s >= 80 else ("Middle" if s >= 50 else "Weak"))))

        def style(row):
            styles = [""] * len(row)
            score = row["RS 1-99"]
            si = row.index.get_loc("Strength")
            ri = row.index.get_loc("RS 1-99")
            if pd.isna(score):
                fg = "#7d8796"
            elif score >= 80:
                fg = "#35d07f"
            elif score >= 50:
                fg = "#f3b94b"
            else:
                fg = "#ff6673"
            s = f"color:{fg};font-weight:700;"
            styles[si] = s
            styles[ri] = s
            return styles

        show["TradingView"] = show["INDEX"].map(lambda x: f"https://www.tradingview.com/chart/?symbol=NSE%3A{x}")

        all_columns = list(show.columns)
        saved_columns = st.session_state.get("index_columns", all_columns)
        saved_columns = [c for c in saved_columns if c in all_columns] or all_columns
        shown_for_table = show[saved_columns]
        full_table = show.copy()

        st.markdown('<div class="table-action-row">', unsafe_allow_html=True)
        action_spacer, view_action, download_action, full_action = st.columns([9.25, 0.42, 0.42, 0.42], gap="small")
        with view_action:
            if st.button("", icon=":material/view_column:", type="tertiary", width=28, key="index_column_view", help="View columns"):
                index_column_selector(all_columns, saved_columns)
        with download_action:
            st.download_button("", full_table.to_csv(index=False).encode("utf-8"), "nifty_index_rs.csv", "text/csv", icon=":material/download:", type="tertiary", width=28, key="index_download_csv", help="Download full table CSV")
        with full_action:
            if st.button("", icon=":material/fullscreen:", type="tertiary", width=28, key="index_fullscreen_action", help="Full table view"):
                st.session_state.index_full_table = True
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.dataframe(
            shown_for_table.style.apply(style, axis=1),
            use_container_width=True,
            hide_index=True,
            height=min(700, 95 + max(len(shown_for_table), 1) * 36),
            column_config={
                "Rank": st.column_config.NumberColumn("#", width="small"),
                "INDEX": st.column_config.TextColumn("INDEX", width="medium"),
                "Strength": st.column_config.TextColumn("STRENGTH", width="small"),
                "RS 1-99": st.column_config.NumberColumn("RS", format="%d", width="small"),
                "Raw RS": st.column_config.NumberColumn("RAW RS", format="%.2f", width="small"),
                "3M %": st.column_config.NumberColumn("3M", format="%.2f"),
                "6M %": st.column_config.NumberColumn("6M", format="%.2f"),
                "9M %": st.column_config.NumberColumn("9M", format="%.2f"),
                "12M %": st.column_config.NumberColumn("12M", format="%.2f"),
                "LTP": st.column_config.NumberColumn("LTP", format="₹%.2f"),
                "Bars": st.column_config.NumberColumn("BARS", format="%d", width="small"),
                "First Date": st.column_config.DateColumn("FIRST DATE", format="DD MMM YYYY", width="medium"),
                "Latest Date": st.column_config.DateColumn("LATEST DATE", format="DD MMM YYYY", width="medium"),
                "Status": st.column_config.TextColumn("STATUS", width="small"),
                "TradingView": st.column_config.LinkColumn("CHART", display_text="Open ↗", width="small"),
            },
        )

        st.markdown(f'<div class="table-foot">Showing {len(shown_for_table):,} of {len(df):,} indices · sorted by RS</div>', unsafe_allow_html=True)
        st.markdown('<div class="legend"><span class="dot" style="background:#35d07f"></span>Strong 80–99 <span class="dot" style="background:#f3b94b"></span>Middle 50–79 <span class="dot" style="background:#ff6673"></span>Weak 1–49</div>', unsafe_allow_html=True)
        st.markdown('<div class="footer">TradingView daily bars · 63 / 126 / 189 / 252 trading bars · weighted 40% / 20% / 20% / 20% · Pine-compatible 1–99 ranking.</div>', unsafe_allow_html=True)

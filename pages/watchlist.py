import re
from io import StringIO
from urllib.parse import quote

import altair as alt
import cloudscraper
import pandas as pd
import streamlit as st

from insights_data import fetch_nse, fetch_screener, search_screener
from insights_deals import fetch_nse_historical_deals

NSE_BASE = "https://www.nseindia.com"

st.markdown('<div class="page-brand"><span>PIPS</span>GOX</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="page-head"><div class="page-title">Insights</div>'
    '<div class="page-sub">Fundamental, ownership and market-position intelligence</div></div>',
    unsafe_allow_html=True,
)

with st.form("insights_search", clear_on_submit=False):
    query = st.text_input(
        "Search stock",
        value=str(st.query_params.get("symbol", "")).strip().upper(),
        placeholder="Search NSE symbol or company name…",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("Search", type="primary", use_container_width=False)

if submitted:
    clean_query = query.strip().upper()
    if clean_query:
        try:
            matches = search_screener(clean_query)
        except Exception as exc:
            st.error(f"Unable to search Screener. ({exc})")
            st.stop()
        if not matches:
            st.warning(f"No company found for '{clean_query}'.")
            st.stop()
        selected = matches[0]
        symbol = str(selected.get("url", "")).split("/company/")[-1].strip("/").split("/")[0].upper() or clean_query
        st.query_params["symbol"] = symbol
        st.session_state["insights_symbol"] = symbol
        st.rerun()

symbol = str(st.session_state.get("insights_symbol", st.query_params.get("symbol", ""))).strip().upper()
if not symbol:
    st.markdown(
        '<div class="empty-state"><div class="empty-title">Search a stock to open Insights</div>'
        '<div class="empty-sub">Data is fetched on demand from NSE and Screener.in. No scanner calculations are changed.</div></div>',
        unsafe_allow_html=True,
    )
    st.stop()

st.query_params["symbol"] = symbol


@st.cache_data(ttl=900, show_spinner=False)
def cached_screener(stock):
    return fetch_screener(stock)


@st.cache_data(ttl=300, show_spinner=False)
def cached_nse(stock):
    return fetch_nse(stock)


@st.cache_data(ttl=900, show_spinner=False)
def cached_deals(stock):
    return fetch_nse_historical_deals(stock, days=365)


@st.cache_data(ttl=900, show_spinner=False)
def cached_corporate_actions(stock):
    url = f"{NSE_BASE}/companies-listing/corporate-filings-actions?symbol={quote(stock)}&tabIndex=equity"
    try:
        session = cloudscraper.create_scraper(browser="chrome")
        response = session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{NSE_BASE}/",
            },
            timeout=20,
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
        for table in tables:
            columns = [str(c).strip() for c in table.columns]
            upper = {c.upper() for c in columns}
            if "PURPOSE" in upper and "EX-DATE" in upper:
                table = table.copy()
                table.columns = columns
                keep = [c for c in ["PURPOSE", "FACE VALUE", "EX-DATE", "RECORD DATE", "BOOK CLOSURE START DATE", "BOOK CLOSURE END DATE"] if c in table.columns]
                if keep:
                    return table[keep].dropna(how="all").reset_index(drop=True)
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _unique_columns(frame):
    if frame.empty:
        return frame
    result = frame.copy()
    seen = {}
    columns = []
    for column in result.columns:
        name = str(column)
        count = seen.get(name, 0)
        seen[name] = count + 1
        columns.append(name if count == 0 else f"{name}.{count}")
    result.columns = columns
    return result


def _moneycontrol_pe_history(moneycontrol):
    ratios = (moneycontrol or {}).get("ratios")
    if not isinstance(ratios, pd.DataFrame) or ratios.empty:
        return pd.DataFrame()
    for _, row in ratios.iterrows():
        label = str(row.iloc[0]).strip().lower()
        if label not in {"p/e", "p/e (x)", "p/e(x)"}:
            continue
        rows = []
        for column, value in row.iloc[1:].items():
            match = re.search(r"(20\d{2})", str(column))
            number = pd.to_numeric(str(value).replace(",", "").replace("—", ""), errors="coerce")
            if match and pd.notna(number) and float(number) > 0:
                year = int(match.group(1))
                rows.append({"Date": pd.Timestamp(year=year, month=3, day=31), "P/E": float(number)})
        if rows:
            return pd.DataFrame(rows).sort_values("Date").tail(6).reset_index(drop=True)
    return pd.DataFrame()


def _deal_columns(frame, short=False):
    if frame.empty:
        return frame
    if short:
        preferred = ["date", "symbol", "securityName", "qty"]
    else:
        preferred = ["date", "symbol", "securityName", "clientName", "buySell", "qty", "watp", "remarks"]
    columns = [column for column in preferred if column in frame.columns]
    return _unique_columns(frame[columns] if columns else frame)


try:
    with st.spinner(f"Loading {symbol} Insights…"):
        screener = cached_screener(symbol)
        nse = cached_nse(symbol)
        deals = cached_deals(symbol)
        corporate_actions = cached_corporate_actions(symbol)
except Exception as exc:
    st.error(f"Unable to load Insights for {symbol}. ({exc})")
    st.stop()

company_name = screener.get("company_name") or symbol
sector = nse.get("sector") or screener.get("sector") or "—"
industry = nse.get("industry") or screener.get("industry") or "—"

st.markdown(
    f'<div class="page-head"><div class="page-title">{company_name}</div>'
    f'<div class="page-sub">{symbol} · {sector} · {industry}</div></div>',
    unsafe_allow_html=True,
)

st.markdown('<div class="section-title">Valuation & company snapshot</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns(3, gap="small")
with c1:
    st.metric("P/E", f"{screener.get('pe'):.2f}" if screener.get("pe") is not None else "—")
with c2:
    market_cap = nse.get("market_cap") or screener.get("market_cap")
    st.metric("Market Cap", f"₹{market_cap:,.0f} Cr" if market_cap is not None else "—")
with c3:
    st.metric("LTP", f"₹{nse.get('ltp'):,.2f}" if nse.get("ltp") is not None else "—")

pe_history = screener.get("pe_history")
pe_source_note = "Screener PE-EPS history."
if not isinstance(pe_history, pd.DataFrame) or pe_history.empty:
    pe_history = _moneycontrol_pe_history(screener.get("moneycontrol"))
    pe_source_note = "Screener PE-EPS history was unavailable; annual P/E history is shown from Moneycontrol as a fallback."

if isinstance(pe_history, pd.DataFrame) and not pe_history.empty:
    st.markdown('<div class="section-title">Historical P/E</div>', unsafe_allow_html=True)
    pe_chart_data = pe_history.copy()
    pe_chart_data["Date"] = pd.to_datetime(pe_chart_data["Date"], errors="coerce")
    pe_chart_data["P/E"] = pd.to_numeric(pe_chart_data["P/E"], errors="coerce")
    pe_chart_data = pe_chart_data.dropna(subset=["Date", "P/E"]).sort_values("Date")
    if not pe_chart_data.empty:
        current_pe = screener.get("pe")
        median_pe = float(pe_chart_data["P/E"].median())
        q1_pe = float(pe_chart_data["P/E"].quantile(0.25))
        q3_pe = float(pe_chart_data["P/E"].quantile(0.75))
        m1, m2, m3, m4 = st.columns(4, gap="small")
        with m1:
            st.metric("Current P/E", f"{current_pe:.2f}" if current_pe is not None else "—")
        with m2:
            st.metric("History Median", f"{median_pe:.2f}")
        with m3:
            st.metric("25th Percentile", f"{q1_pe:.2f}")
        with m4:
            st.metric("75th Percentile", f"{q3_pe:.2f}")
        median_rule = alt.Chart(pd.DataFrame({"P/E": [median_pe]})).mark_rule(strokeDash=[5, 5]).encode(y=alt.Y("P/E:Q"))
        pe_line = (
            alt.Chart(pe_chart_data)
            .mark_line(point=True)
            .encode(
                x=alt.X("Date:T", title=None, axis=alt.Axis(format="YYYY", labelAngle=0)),
                y=alt.Y("P/E:Q", title="P/E", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("Date:T", title="Date", format="dd MMM YYYY"), alt.Tooltip("P/E:Q", title="P/E", format=".2f")],
            )
        )
        st.altair_chart((median_rule + pe_line).properties(height=300).interactive(), use_container_width=True)
        st.caption(pe_source_note)
else:
    st.info("Historical P/E is not available from the available public data sources for this company.")

growth = screener.get("growth")
if isinstance(growth, pd.DataFrame) and not growth.empty:
    st.markdown('<div class="section-title">Growth & margin trend · quarterly YoY</div>', unsafe_allow_html=True)
    chart_data = growth.copy()
    chart_data["Quarter"] = pd.to_datetime(chart_data["Quarter"], format="%b %Y")
    chart_data = chart_data.sort_values("Quarter").rename(columns={"Sales Growth": "Sales Growth %", "Earning Growth": "Earning Growth %", "Margin": "Margin %"})
    chart_data = chart_data.melt(id_vars=["Quarter"], value_vars=["Sales Growth %", "Earning Growth %", "Margin %"], var_name="Metric", value_name="Value").dropna(subset=["Value"])
    chart = (
        alt.Chart(chart_data)
        .mark_line(point=True)
        .encode(
            x=alt.X("Quarter:T", title=None, axis=alt.Axis(format="MMM YY", labelAngle=0)),
            y=alt.Y("Value:Q", title="%", scale=alt.Scale(zero=True)),
            color=alt.Color("Metric:N", title=None),
            tooltip=[alt.Tooltip("Quarter:T", title="Quarter", format="MMM YYYY"), alt.Tooltip("Metric:N", title="Metric"), alt.Tooltip("Value:Q", title="Value", format=".2f")],
        )
        .properties(height=330)
        .interactive()
    )
    st.altair_chart(chart, use_container_width=True)
    st.caption("Sales Growth and Earning Growth are YoY growth rates calculated from Screener quarterly figures. Margin is OPM when available; otherwise it is derived from net profit / sales.")
else:
    st.info("Quarterly growth history is not available from Screener for this company.")

st.markdown('<div class="section-title">Corporate actions · NSE</div>', unsafe_allow_html=True)
if isinstance(corporate_actions, pd.DataFrame) and not corporate_actions.empty:
    st.dataframe(_unique_columns(corporate_actions), use_container_width=True, hide_index=True, height=min(420, 80 + len(corporate_actions) * 36))
else:
    st.caption("NSE corporate-action history could not be loaded from this app server right now.")
    st.link_button("Open NSE corporate actions ↗", f"{NSE_BASE}/companies-listing/corporate-filings-actions?symbol={quote(symbol)}&tabIndex=equity")

deal_data = deals or {}
bulk_df = deal_data.get("bulk", pd.DataFrame())
block_df = deal_data.get("block", pd.DataFrame())
short_df = deal_data.get("short_selling", pd.DataFrame())

st.markdown('<div class="section-title">NSE institutional activity · last 1 year</div>', unsafe_allow_html=True)
st.caption(f"Historical window: {deal_data.get('from_date', '—')} to {deal_data.get('to_date', '—')}. Data is queried from NSE historical Bulk Deals, Block Deals and Short Selling reports.")

if not any(isinstance(frame, pd.DataFrame) and not frame.empty for frame in (bulk_df, block_df, short_df)):
    st.caption("No matching NSE historical activity was returned for this symbol in the selected one-year window.")
    st.link_button("Open NSE Bulk / Block / Short Selling archive ↗", f"{NSE_BASE}/report-detail/display-bulk-and-block-deals#")
else:
    tabs = st.tabs(["Bulk deals", "Block deals", "Short selling"])
    with tabs[0]:
        if isinstance(bulk_df, pd.DataFrame) and not bulk_df.empty:
            st.dataframe(_deal_columns(bulk_df), use_container_width=True, hide_index=True, height=min(420, 90 + len(bulk_df) * 36))
        else:
            st.caption("No bulk-deal records for this symbol in the last 1 year.")
    with tabs[1]:
        if isinstance(block_df, pd.DataFrame) and not block_df.empty:
            st.dataframe(_deal_columns(block_df), use_container_width=True, hide_index=True, height=min(420, 90 + len(block_df) * 36))
        else:
            st.caption("No block-deal records for this symbol in the last 1 year.")
    with tabs[2]:
        if isinstance(short_df, pd.DataFrame) and not short_df.empty:
            st.dataframe(_deal_columns(short_df, short=True), use_container_width=True, hide_index=True, height=min(420, 90 + len(short_df) * 36))
        else:
            st.caption("No short-selling records for this symbol in the last 1 year.")

st.markdown('<div class="section-title">Shareholders</div>', unsafe_allow_html=True)
shareholders = screener.get("shareholders")
if isinstance(shareholders, pd.DataFrame) and not shareholders.empty:
    st.dataframe(_unique_columns(shareholders), use_container_width=True, hide_index=True, height=300)
else:
    st.info("Shareholding pattern is not available from the Screener company page.")

st.markdown('<div class="section-title">Market position</div>', unsafe_allow_html=True)
left, right = st.columns([1.15, 2.85], gap="large")
with left:
    st.markdown(f"**Sector**  \n{sector}")
    st.markdown(f"**Industry**  \n{industry}")
    indices = nse.get("indices") or []
    if indices:
        st.markdown("**NSE indices**")
        st.caption(", ".join(indices))

with right:
    peers = screener.get("peers")
    if isinstance(peers, pd.DataFrame) and not peers.empty:
        peer_display = _unique_columns(peers.copy())
        first_col = peer_display.columns[0]
        if first_col != "Company" and "Company" in peer_display.columns:
            peer_display = peer_display.rename(columns={"Company": "Peer Company"})
        peer_display = peer_display.rename(columns={first_col: "Company"})
        peer_display = _unique_columns(peer_display)
        st.dataframe(peer_display, use_container_width=True, hide_index=True, height=330)
    else:
        st.info("Peer comparison is not available from Screener for this company.")

st.markdown('<div class="section-title">Company website</div>', unsafe_allow_html=True)
website = screener.get("website")
if website:
    st.link_button("Open company website ↗", website)
else:
    st.caption("Company website was not available in the Screener listing.")

st.caption("Sources: NSE India for quote, classification, corporate actions and historical deal activity; Screener.in for valuation, financial trends, shareholding, peers and website; Moneycontrol only as the historical P/E fallback. No scanner calculations are changed.")
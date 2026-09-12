import reflex as rx
import pandas as pd
from insights_data import fetch_screener, fetch_nse, search_screener
from insights_deals import fetch_nse_historical_deals
from reflex_ui import shell, table_from_rows

class InsightsState(rx.State):
    symbol: str = ""
    query: str = ""
    status: str = "Search a stock to open Insights"
    rows: list[dict] = []
    def set_query(self,v): self.query=v
    def load(self):
        self.status="Loading Insights…"
        try:
            q=self.query.strip().upper()
            matches=search_screener(q)
            if matches:
                self.symbol=str(matches[0].get("url","")).split("/company/")[-1].strip("/").split("/")[0].upper() or q
            else:
                self.symbol=q
            s=fetch_screener(self.symbol); n=fetch_nse(self.symbol); fetch_nse_historical_deals(self.symbol,days=365)
            data={"Company":s.get("company_name") or self.symbol,"Sector":n.get("sector") or s.get("sector") or "—","Industry":n.get("industry") or s.get("industry") or "—","P/E":s.get("pe") or "—","LTP":n.get("ltp") or "—","Market Cap":n.get("market_cap") or s.get("market_cap") or "—"}
            self.rows=[data]
            self.status=f"Loaded {self.symbol}"
        except Exception as e:
            self.status=f"Unable to load Insights: {e}"

def insights_page():
    headers=["Company","Sector","Industry","P/E","LTP","Market Cap"]
    return shell(rx.heading("Insights",size="6"),rx.text("Fundamental, ownership and market-position intelligence",color="gray"),rx.hstack(rx.input(placeholder="Search NSE symbol or company name…",value=InsightsState.query,on_change=InsightsState.set_query),rx.button("Search",on_click=InsightsState.load)),rx.text(InsightsState.status),rx.cond(InsightsState.rows.length()>0,table_from_rows(headers,InsightsState.rows),rx.text("Data is fetched on demand from NSE and Screener.in.")),title="PIPSGOX")

import reflex as rx
import pandas as pd
import vcp_engine
from reflex_ui import shell, table_from_rows

class VCPState(rx.State):
    rows: list[dict] = []
    status: str = "Ready"
    trend_filter: bool = True
    near_high: float = 5
    low_pct: float = 70
    def scan(self):
        self.status="Running VCP scan…"
        try:
            df, stats=vcp_engine.run_scan(trend_filter=self.trend_filter,use_52w_high=True,near_high_pct=self.near_high,use_52w_low=False,prior_low_pct=self.low_pct,dma_position_filter=True,dma_position_pct=15,batch_size=vcp_engine.DEFAULT_BATCH_SIZE,snapshot_mode="eod")
            self.rows=df.where(pd.notna(df),None).to_dict("records")
            self.status=f"Scan complete · {len(self.rows)} matches"
        except Exception as e:self.status=f"Scan failed: {e}"

def vcp_page():
    headers=["Symbol","Index","Industry","LTP","52W High","From 52W High %","52W Low","From 52W Low %","50DMA","Price vs 50DMA %","150DMA","200DMA"]
    return shell(rx.heading("VCP Type Scan",size="6"),rx.text("Trend · 52W position · 50DMA position",color="gray"),rx.hstack(rx.checkbox("Trend filter",value=VCPState.trend_filter),rx.text("Within 52W High %"),rx.number_input(value=VCPState.near_high,min=0,max=10),rx.button("▶ After Market Scan",on_click=VCPState.scan)),rx.text(VCPState.status),rx.cond(VCPState.rows.length()>0,table_from_rows(headers,VCPState.rows),rx.text("Run a VCP scan to see results.")),title="PIPSGOX")

import reflex as rx
import pandas as pd
import rs_engine
from fno_stocks import filter_fno_results
from reflex_ui import shell, table_from_rows

class StockState(rx.State):
    rows: list[dict] = []
    status: str = "Ready"
    min_rs: int = 80
    near_high: float = 5
    min_price: float = 100
    use_minervini: bool = True
    def set_min_rs(self, v): self.min_rs = int(v)
    def set_near_high(self, v): self.near_high = float(v)
    def set_min_price(self, v): self.min_price = float(v)
    def scan(self):
        self.status = "Running stock scan…"
        try:
            df, stats = rs_engine.run_scan(min_rs=self.min_rs, near_high_pct=self.near_high, min_price=self.min_price, use_minervini=self.use_minervini, use_ma_rising=False, rising_days=20, batch_size=rs_engine.DEFAULT_BATCH_SIZE, snapshot_mode="eod", use_min_rs=True, use_near_high=True, use_min_price=True)
            try:
                fno = filter_fno_results(df)
                syms = set(fno["Symbol"].astype(str).str.upper()) if fno is not None and not fno.empty else set()
                df = df.loc[~df["Symbol"].astype(str).str.upper().isin(syms)]
            except Exception: pass
            self.rows = df.where(pd.notna(df), None).to_dict("records")
            self.status = f"Scan complete · {len(self.rows)} matches"
        except Exception as e: self.status = f"Scan failed: {e}"

@rx.page
def stock_page():
    headers=["Symbol","Index","Industry","LTP","RS Rating","3M %","6M %","9M %","12M %","52W High","From 52W High %"]
    return shell(
        rx.heading("Stock RS + Technical", size="6"),
        rx.text("IBD-style RS ranking with configurable scan filters", color="gray"),
        rx.hstack(rx.text("Minimum RS"),rx.number_input(value=StockState.min_rs,on_change=StockState.set_min_rs,min=50,max=99),rx.text("Near 52W high %"),rx.number_input(value=StockState.near_high,on_change=StockState.set_near_high,min=1,max=25),rx.text("Minimum price"),rx.number_input(value=StockState.min_price,on_change=StockState.set_min_price,min=1)),
        rx.button("▶ After Market Scan", on_click=StockState.scan),
        rx.text(StockState.status),
        rx.cond(StockState.rows.length()>0,table_from_rows(headers,StockState.rows),rx.text("Run a scan to see results.")),
        title="PIPSGOX"
    )

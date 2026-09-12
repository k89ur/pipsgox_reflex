import reflex as rx
import pandas as pd
from index_rs_engine import run_index_scan
from reflex_ui import shell, table_from_rows

class IndexState(rx.State):
    rows: list[dict] = []
    status: str = "Ready"
    running: bool = False
    def scan(self):
        self.running = True
        self.status = "Running Index RS scan…"
        try:
            df, stats = run_index_scan()
            self.rows = df.where(pd.notna(df), None).to_dict("records")
            self.status = f"Scan complete · {len(self.rows)} indices"
        except Exception as e:
            self.status = f"Scan failed: {e}"
        self.running = False

def index_page():
    headers = ["Rank", "INDEX", "RS 1-99", "Raw RS", "3M %", "6M %", "9M %", "12M %", "LTP", "Status"]
    return shell(
        rx.heading("NIFTY Relative Strength", size="6"),
        rx.text("28 industries · IBD-style relative strength · Pine-compatible daily calculation", color="gray"),
        rx.button("↻ Refresh Index RS", on_click=IndexState.scan, loading=IndexState.running),
        rx.text(IndexState.status),
        rx.cond(IndexState.rows.length() > 0, table_from_rows(headers, IndexState.rows), rx.text("Press Refresh to calculate the index universe.")),
        title="PIPSGOX"
    )

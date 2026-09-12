import reflex as rx
from .pages.index_rs import index_page
from .pages.stock_rs import stock_page
from .pages.vcp_scan import vcp_page
from .pages.watchlist import insights_page

class AppState(rx.State):
    """Global UI state. Scan engines remain plain Python modules."""
    pass

app = rx.App()
app.add_page(index_page, route="/index-rs", title="Index RS")
app.add_page(stock_page, route="/stock-rs", title="Stock RS + Technical")
app.add_page(vcp_page, route="/vcp-scan", title="VCP Scan")
app.add_page(insights_page, route="/insights", title="Insights")

# PipsGoX Reflex

Reflex conversion of the PipsGoX Streamlit scanner. The calculation/data engines are preserved; the application UI and interaction layer run on Reflex.

## Pages
- Index RS
- Stock RS + Technical
- VCP Type Scan
- Insights

## Run
```bash
pip install -r requirements.txt
reflex run --env prod
```

Reflex frontend: port 3000. Backend: port 8000.

The scanner engines (`rs_engine.py`, `vcp_engine.py`, `index_rs_engine.py`, NSE/Screener data modules and F&O filtering) remain the backend/data layer. Streamlit is no longer required by the UI.

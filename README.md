# PIPSGOX — Reflex

Reflex conversion of the PIPSGOX Streamlit application.

## Run

```bash
pip install -r requirements.txt
reflex init
reflex run
```

Frontend: port 3000. Backend: port 8000.

## Pages

- `/` — Index RS
- `/index-rs` — NIFTY Relative Strength
- `/stock-rs` — Stock RS + Technical
- `/vcp-scan` — VCP Type Scan
- `/insights` — Fundamental / ownership / market insights

## Architecture

The Streamlit presentation layer has been replaced with native Reflex components and state. Existing market-data and scanner engines remain ordinary Python modules and are called by Reflex backend event handlers. Calculation logic is kept in the existing engines rather than duplicated in the UI.

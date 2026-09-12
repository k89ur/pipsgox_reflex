# NIFTY Index Relative Strength

Minimal Streamlit app that reproduces the supplied Pine Script's 28-index IBD-style RS calculation.

## Calculation

- Exact 28-index universe from the supplied script
- NIFTY 50 benchmark
- 63 trading bars: 40%
- 126 trading bars: 20%
- 189 trading bars: 20%
- 252 trading bars: 20%
- Relative performance = index return minus NIFTY 50 return
- RS 1–99 = the supplied Pine percentile/ranking formula

## Data

The app uses NSE historical index data as the primary source rather than guessing Yahoo Finance ticker mappings. Missing NSE series are reported as unavailable; they are never replaced with another instrument.

## Run in GitHub Codespaces

```bash
pip install -r requirements.txt
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

Open forwarded port **8501**.

The first page load automatically runs the scan. **Refresh RS** forces a fresh NSE download.

## Important

This is an IBD-style approximation based on the supplied Pine formula. It is not IBD's proprietary RS Rating.

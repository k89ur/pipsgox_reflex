import io
import requests
import pandas as pd

FNO_CSV_URL = "https://drive.google.com/uc?export=download&id=1urIdJJ8L3DJGuuNvt49azQ62O0pDKj9e"


def load_fno_symbols(timeout=15):
    """Fetch the external F&O CSV and return a normalized symbol set."""
    response = requests.get(FNO_CSV_URL, timeout=timeout)
    response.raise_for_status()
    data = pd.read_csv(io.BytesIO(response.content))
    if "SYMBOL" not in data.columns:
        raise ValueError("F&O CSV must contain a SYMBOL column.")
    symbols = data["SYMBOL"].astype(str).str.strip().str.upper()
    symbols = symbols[symbols.ne("") & symbols.ne("NAN")]
    return set(symbols.tolist())


def filter_fno_results(df, timeout=15):
    """Partition an existing scan result into non-F&O main rows and F&O rows.

    The returned dataframe contains the F&O subset. The original scan dataframe
    is reduced in place to the non-F&O subset so the existing Main Results view
    automatically excludes stocks shown in the F&O table.
    """
    if df is None:
        return pd.DataFrame()
    if df.empty:
        return df.copy()

    symbols = load_fno_symbols(timeout=timeout)
    normalized = df["Symbol"].astype(str).str.strip().str.upper()
    fno_mask = normalized.isin(symbols)
    fno_result = df.loc[fno_mask].copy()

    # Keep the existing scan dataframe object, but partition its result rows.
    df.drop(index=df.index[fno_mask], inplace=True)
    return fno_result

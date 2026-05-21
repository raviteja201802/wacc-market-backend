from __future__ import annotations

from datetime import date, datetime, timedelta
from time import sleep

import pandas as pd
import yfinance as yf

from app.services.excel_service import read_sheet, utc_now
from app.utils.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)

INDEXES = {
    "^NSEI": "NIFTY 50",
    "^BSESN": "Sensex",
}


def latest_date_for_symbol(df: pd.DataFrame, symbol_column: str, symbol: str) -> date | None:
    if df.empty or symbol_column not in df or "Date" not in df:
        return None
    rows = df[df[symbol_column].astype(str).eq(symbol)]
    if rows.empty:
        return None
    parsed = pd.to_datetime(rows["Date"], errors="coerce").dropna()
    if parsed.empty:
        return None
    return parsed.max().date()


def download_ohlcv(ticker: str, start: date, end: date) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(settings.yahoo_retry_count + 1):
        try:
            data = yf.download(
                ticker,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return data.reset_index()
        except Exception as exc:
            last_error = exc
            sleep(1 + attempt)
    raise RuntimeError(f"Unable to download {ticker}: {last_error}")


def rows_from_yahoo(data: pd.DataFrame, ticker: str, nse_symbol: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    updated_at = utc_now()
    result = pd.DataFrame(
        {
            "Date": pd.to_datetime(data["Date"]).dt.date.astype(str),
            "Ticker": ticker,
            "NSESymbol": nse_symbol,
            "Open": data.get("Open"),
            "High": data.get("High"),
            "Low": data.get("Low"),
            "Close": data.get("Close"),
            "AdjClose": data.get("Adj Close", data.get("Close")),
            "Volume": data.get("Volume"),
            "Source": "Yahoo Finance via yfinance",
            "UpdatedAt": updated_at,
        }
    )
    return result.dropna(subset=["Date", "Close"])


def update_price_history(company_master: pd.DataFrame) -> tuple[pd.DataFrame, list[str], int]:
    existing = read_sheet("PRICE_HISTORY")
    active = company_master[company_master["ActiveStatus"].astype(str).str.lower().eq("active")]
    if settings.max_company_refresh > 0:
        active = active.head(settings.max_company_refresh)

    frames = [existing]
    failed: list[str] = []
    total_added = 0
    today = date.today()
    default_start = today - timedelta(days=365 * settings.default_history_years)

    for row in active.itertuples(index=False):
        ticker = str(getattr(row, "Ticker", "")).strip()
        nse_symbol = str(getattr(row, "NSESymbol", "")).strip()
        if not ticker or ticker == "nan":
            continue
        last_date = latest_date_for_symbol(existing, "Ticker", ticker)
        start = (last_date + timedelta(days=1)) if last_date else default_start
        if start > today:
            continue
        try:
            data = download_ohlcv(ticker, start, today)
            rows = rows_from_yahoo(data, ticker, nse_symbol)
            total_added += len(rows)
            if not rows.empty:
                frames.append(rows)
        except Exception as exc:
            logger.warning("Price update failed for %s: %s", ticker, exc)
            failed.append(ticker)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    combined = combined.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    return combined, failed, total_added


def update_market_index() -> tuple[pd.DataFrame, list[str], int]:
    existing = read_sheet("MARKET_INDEX")
    frames = [existing]
    failed: list[str] = []
    total_added = 0
    today = date.today()
    default_start = today - timedelta(days=365 * settings.default_history_years)

    for ticker, name in INDEXES.items():
        last_date = latest_date_for_symbol(existing, "IndexTicker", ticker)
        start = (last_date + timedelta(days=1)) if last_date else default_start
        if start > today:
            continue
        try:
            data = download_ohlcv(ticker, start, today)
            if data.empty:
                continue
            updated_at = utc_now()
            rows = pd.DataFrame(
                {
                    "Date": pd.to_datetime(data["Date"]).dt.date.astype(str),
                    "IndexTicker": ticker,
                    "IndexName": name,
                    "Open": data.get("Open"),
                    "High": data.get("High"),
                    "Low": data.get("Low"),
                    "Close": data.get("Close"),
                    "AdjClose": data.get("Adj Close", data.get("Close")),
                    "Volume": data.get("Volume"),
                    "Source": "Yahoo Finance via yfinance",
                    "UpdatedAt": updated_at,
                }
            )
            rows = rows.dropna(subset=["Date", "Close"])
            total_added += len(rows)
            frames.append(rows)
        except Exception as exc:
            logger.warning("Index update failed for %s: %s", ticker, exc)
            failed.append(ticker)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date", "IndexTicker"], keep="last")
    combined = combined.sort_values(["IndexTicker", "Date"]).reset_index(drop=True)
    return combined, failed, total_added


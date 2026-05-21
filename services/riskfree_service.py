from __future__ import annotations

from datetime import date

import pandas as pd
import yfinance as yf

from app.services.excel_service import read_sheet, utc_now
from app.utils.logger import get_logger


logger = get_logger(__name__)


def fetch_india_10y_yield() -> pd.DataFrame:
    today = date.today().isoformat()
    updated_at = utc_now()
    try:
        ticker = yf.Ticker("^IN10Y")
        history = ticker.history(period="5d")
        if not history.empty and "Close" in history:
            rate = float(history["Close"].dropna().iloc[-1])
            return pd.DataFrame(
                [
                    {
                        "Date": today,
                        "Country": "India",
                        "Tenor": "10Y",
                        "Rate": rate,
                        "Source": "Yahoo Finance ^IN10Y",
                        "UpdatedAt": updated_at,
                        "Notes": "Automatic fetch",
                    }
                ]
            )
    except Exception as exc:
        logger.warning("Risk-free rate fetch failed: %s", exc)

    return pd.DataFrame(
        [
            {
                "Date": today,
                "Country": "India",
                "Tenor": "10Y",
                "Rate": "",
                "Source": "Fallback",
                "UpdatedAt": updated_at,
                "Notes": "Automatic fetch failed. Review source before valuation use.",
            }
        ]
    )


def update_risk_free_rate() -> tuple[pd.DataFrame, int]:
    existing = read_sheet("RISK_FREE_RATE")
    incoming = fetch_india_10y_yield()
    combined = pd.concat([existing, incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date", "Country", "Tenor"], keep="last")
    combined = combined.sort_values(["Country", "Tenor", "Date"]).reset_index(drop=True)
    return combined, len(incoming)


from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def run_validation_checks(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    today = date.today()
    rows: list[dict[str, str]] = []
    price_history = sheets.get("PRICE_HISTORY", pd.DataFrame())
    company_master = sheets.get("COMPANY_MASTER", pd.DataFrame())

    if not price_history.empty:
        duplicates = price_history.duplicated(subset=["Date", "Ticker"]).sum()
        rows.append(
            {
                "CheckDate": today.isoformat(),
                "Ticker": "ALL",
                "CheckType": "Duplicate price rows",
                "Status": "PASS" if duplicates == 0 else "WARN",
                "Details": f"{duplicates} duplicate Date/Ticker rows detected",
            }
        )

        missing_close = price_history["Close"].isna().sum()
        rows.append(
            {
                "CheckDate": today.isoformat(),
                "Ticker": "ALL",
                "CheckType": "Missing close prices",
                "Status": "PASS" if missing_close == 0 else "WARN",
                "Details": f"{missing_close} rows have missing Close values",
            }
        )

    if not company_master.empty and not price_history.empty:
        stale_cutoff = today - timedelta(days=10)
        grouped = price_history.copy()
        grouped["ParsedDate"] = pd.to_datetime(grouped["Date"], errors="coerce")
        latest = grouped.dropna(subset=["ParsedDate"]).groupby("Ticker")["ParsedDate"].max()
        active = company_master[
            company_master["ActiveStatus"].astype(str).str.lower().eq("active")
        ]
        for row in active.itertuples(index=False):
            ticker = str(getattr(row, "Ticker", ""))
            last_price_date = latest.get(ticker)
            if pd.isna(last_price_date) or last_price_date.date() < stale_cutoff:
                rows.append(
                    {
                        "CheckDate": today.isoformat(),
                        "Ticker": ticker,
                        "CheckType": "Stale company price data",
                        "Status": "WARN",
                        "Details": f"Latest price date: {last_price_date}",
                    }
                )

    if not rows:
        rows.append(
            {
                "CheckDate": today.isoformat(),
                "Ticker": "ALL",
                "CheckType": "General validation",
                "Status": "PASS",
                "Details": "No validation issues found",
            }
        )

    return pd.DataFrame(rows)


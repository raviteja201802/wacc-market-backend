from __future__ import annotations

from datetime import date
from io import StringIO

import pandas as pd
import requests

from app.services.excel_service import empty_frame, read_sheet, utc_now
from app.utils.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)

NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"


def fetch_nse_company_universe() -> pd.DataFrame:
    headers = {
        "User-Agent": "Mozilla/5.0 WACCMarketDatabase/1.0",
        "Accept": "text/csv,application/csv,*/*",
    }
    try:
        response = requests.get(
            NSE_EQUITY_LIST_URL,
            headers=headers,
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        raw = pd.read_csv(StringIO(response.text))
        universe = normalize_nse_universe(raw, "NSE downloadable CSV")
        universe.to_csv(settings.universe_cache_file, index=False)
        return universe
    except Exception as exc:
        logger.warning("NSE universe fetch failed: %s", exc)
        if settings.universe_cache_file.exists():
            return pd.read_csv(settings.universe_cache_file, dtype=str)
        return empty_frame("COMPANY_MASTER")


def normalize_nse_universe(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    today = date.today().isoformat()
    mapping = {
        "SYMBOL": "NSESymbol",
        "NAME OF COMPANY": "CompanyName",
        " SERIES": "Series",
        "SERIES": "Series",
        " DATE OF LISTING": "ListingDate",
        "DATE OF LISTING": "ListingDate",
        " ISIN NUMBER": "ISIN",
        "ISIN NUMBER": "ISIN",
    }
    raw = raw.rename(columns={col: mapping.get(col, col) for col in raw.columns})
    for column in ["NSESymbol", "CompanyName", "ListingDate", "ISIN"]:
        if column not in raw:
            raw[column] = ""

    if "Series" in raw.columns:
        raw = raw[raw["Series"].astype(str).str.strip().eq("EQ")]

    df = pd.DataFrame(
        {
            "Ticker": raw["NSESymbol"].astype(str).str.strip() + ".NS",
            "NSESymbol": raw["NSESymbol"].astype(str).str.strip(),
            "CompanyName": raw["CompanyName"].astype(str).str.strip(),
            "Exchange": "NSE",
            "Sector": "",
            "Industry": "",
            "ListingDate": raw["ListingDate"].astype(str).str.strip(),
            "ISIN": raw["ISIN"].astype(str).str.strip(),
            "Currency": "INR",
            "ActiveStatus": "Active",
            "FirstSeenDate": today,
            "LastSeenDate": today,
            "DataSource": source,
            "Notes": "",
        }
    )
    return df.drop_duplicates(subset=["NSESymbol"]).reset_index(drop=True)


def detect_new_listings(existing_master: pd.DataFrame, latest_universe: pd.DataFrame) -> pd.DataFrame:
    if existing_master.empty:
        return latest_universe.copy()
    existing_symbols = set(existing_master["NSESymbol"].astype(str))
    return latest_universe[~latest_universe["NSESymbol"].astype(str).isin(existing_symbols)].copy()


def detect_delistings(existing_master: pd.DataFrame, latest_universe: pd.DataFrame) -> pd.DataFrame:
    if existing_master.empty:
        return pd.DataFrame(columns=existing_master.columns)
    latest_symbols = set(latest_universe["NSESymbol"].astype(str))
    return existing_master[~existing_master["NSESymbol"].astype(str).isin(latest_symbols)].copy()


def refresh_company_master() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    existing = read_sheet("COMPANY_MASTER")
    latest = fetch_nse_company_universe()
    if latest.empty:
        return existing, pd.DataFrame(), pd.DataFrame(), latest

    new_listings = detect_new_listings(existing, latest)
    delistings = detect_delistings(existing, latest)
    today = date.today().isoformat()

    if existing.empty:
        master = latest.copy()
    else:
        master = existing.copy()
        master.loc[master["NSESymbol"].isin(latest["NSESymbol"]), "ActiveStatus"] = "Active"
        master.loc[master["NSESymbol"].isin(latest["NSESymbol"]), "LastSeenDate"] = today
        master.loc[master["NSESymbol"].isin(delistings["NSESymbol"]), "ActiveStatus"] = "Inactive"
        master.loc[master["NSESymbol"].isin(delistings["NSESymbol"]), "Notes"] = "Not found in latest NSE universe"
        master = pd.concat([master, new_listings], ignore_index=True)

    snapshot = latest[["NSESymbol", "CompanyName", "ISIN", "Exchange", "DataSource"]].copy()
    snapshot.insert(0, "SnapshotDate", today)
    snapshot["Status"] = "Active"

    logger.info(
        "Universe refresh complete. active=%s new=%s inactive=%s at=%s",
        len(latest),
        len(new_listings),
        len(delistings),
        utc_now(),
    )
    return master, new_listings, delistings, snapshot


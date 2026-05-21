from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from time import sleep
from zipfile import ZipFile

import pandas as pd
import requests

from app.services.excel_service import read_sheet, utc_now
from app.services.price_service import latest_date_for_symbol
from app.utils.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)

MONTH_CODE = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}


def nse_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 WACCMarketDatabase/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/all-reports",
    }


def candidate_bhavcopy_urls(for_date: date) -> list[str]:
    yyyymmdd = for_date.strftime("%Y%m%d")
    ddmonyyyy = f"{for_date.day:02d}{MONTH_CODE[for_date.month]}{for_date.year}"
    return [
        f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F.csv.zip",
        f"https://archives.nseindia.com/content/historical/EQUITIES/{for_date.year}/{MONTH_CODE[for_date.month]}/cm{ddmonyyyy}bhav.csv.zip",
    ]


def download_bhavcopy(for_date: date) -> pd.DataFrame:
    last_error: Exception | None = None
    session = requests.Session()
    for url in candidate_bhavcopy_urls(for_date):
        try:
            response = session.get(
                url,
                headers=nse_headers(),
                timeout=settings.request_timeout_seconds,
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            with ZipFile(BytesIO(response.content)) as zipped:
                csv_names = [name for name in zipped.namelist() if name.lower().endswith(".csv")]
                if not csv_names:
                    continue
                with zipped.open(csv_names[0]) as csv_file:
                    return pd.read_csv(csv_file)
        except Exception as exc:
            last_error = exc
            logger.info("NSE bhavcopy download failed for %s via %s: %s", for_date, url, exc)
    if last_error:
        raise RuntimeError(f"No NSE bhavcopy available for {for_date}: {last_error}")
    raise FileNotFoundError(f"No NSE bhavcopy available for {for_date}")


def normalize_bhavcopy(raw: pd.DataFrame, for_date: date) -> pd.DataFrame:
    raw.columns = [str(col).strip() for col in raw.columns]
    updated_at = utc_now()

    if {"SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"}.issubset(raw.columns):
        equity = raw[raw["SERIES"].astype(str).str.strip().eq("EQ")].copy()
        symbol = equity["SYMBOL"].astype(str).str.strip()
        return pd.DataFrame(
            {
                "Date": for_date.isoformat(),
                "Ticker": symbol + ".NS",
                "NSESymbol": symbol,
                "Open": equity["OPEN"],
                "High": equity["HIGH"],
                "Low": equity["LOW"],
                "Close": equity["CLOSE"],
                "AdjClose": equity["CLOSE"],
                "Volume": equity["TOTTRDQTY"],
                "Source": "NSE equity bhavcopy",
                "UpdatedAt": updated_at,
            }
        )

    if {"TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric"}.issubset(raw.columns):
        equity = raw[raw["SctySrs"].astype(str).str.strip().eq("EQ")].copy()
        symbol = equity["TckrSymb"].astype(str).str.strip()
        volume = equity["TtlTradgVol"] if "TtlTradgVol" in equity.columns else ""
        return pd.DataFrame(
            {
                "Date": for_date.isoformat(),
                "Ticker": symbol + ".NS",
                "NSESymbol": symbol,
                "Open": equity["OpnPric"],
                "High": equity["HghPric"],
                "Low": equity["LwPric"],
                "Close": equity["ClsPric"],
                "AdjClose": equity["ClsPric"],
                "Volume": volume,
                "Source": "NSE common bhavcopy",
                "UpdatedAt": updated_at,
            }
        )

    raise ValueError(f"Unsupported NSE bhavcopy columns: {', '.join(raw.columns[:12])}")


def missing_bhavcopy_dates(existing: pd.DataFrame) -> list[date]:
    today = date.today()
    latest = latest_date_for_symbol(existing, "Ticker", existing["Ticker"].iloc[0]) if not existing.empty else None
    if not existing.empty and "Date" in existing:
        parsed = pd.to_datetime(existing["Date"], errors="coerce").dropna()
        latest = parsed.max().date() if not parsed.empty else latest

    default_start = today - timedelta(days=min(settings.default_history_years * 365, settings.nse_backfill_days))
    start = (latest + timedelta(days=1)) if latest else default_start
    if start > today:
        return []
    return [start + timedelta(days=offset) for offset in range((today - start).days + 1)]


def latest_available_bhavcopy_date() -> date | None:
    today = date.today()
    for offset in range(settings.nse_latest_scan_days + 1):
        candidate = today - timedelta(days=offset)
        try:
            download_bhavcopy(candidate)
            return candidate
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.info("Latest NSE bhavcopy scan skipped %s: %s", candidate, exc)
        sleep(settings.nse_request_pause_seconds)
    return None


def filter_active_symbols(rows: pd.DataFrame, active_symbols: set[str]) -> pd.DataFrame:
    normalized_active = {str(symbol).strip().upper() for symbol in active_symbols}
    rows = rows.copy()
    rows["NSESymbol"] = rows["NSESymbol"].astype(str).str.strip().str.upper()
    rows["Ticker"] = rows["NSESymbol"] + ".NS"
    return rows[rows["NSESymbol"].isin(normalized_active)].copy()


def update_price_history_from_nse(company_master: pd.DataFrame) -> tuple[pd.DataFrame, list[str], int]:
    existing = read_sheet("PRICE_HISTORY")
    active_symbols = set(
        company_master[
            company_master["ActiveStatus"].astype(str).str.lower().eq("active")
        ]["NSESymbol"].astype(str).str.strip().str.upper()
    )
    if settings.max_company_refresh > 0:
        active_symbols = set(list(active_symbols)[: settings.max_company_refresh])

    frames = [existing]
    failed_dates: list[str] = []
    total_added = 0
    skipped_dates = 0

    for for_date in missing_bhavcopy_dates(existing):
        try:
            raw = download_bhavcopy(for_date)
            rows = normalize_bhavcopy(raw, for_date)
            rows = filter_active_symbols(rows, active_symbols)
            if rows.empty:
                continue
            total_added += len(rows)
            frames.append(rows)
        except FileNotFoundError:
            skipped_dates += 1
            continue
        except Exception as exc:
            failed_dates.append(f"NSE_BHAVCOPY_{for_date.isoformat()}")
            logger.warning("NSE price update failed for %s: %s", for_date, exc)
        sleep(settings.nse_request_pause_seconds)

    if total_added == 0 and existing.empty:
        latest = latest_available_bhavcopy_date()
        if latest:
            raw = download_bhavcopy(latest)
            normalized_rows = normalize_bhavcopy(raw, latest)
            rows = filter_active_symbols(normalized_rows, active_symbols)
            if rows.empty:
                failed_dates.append(
                    f"NSE_BHAVCOPY_{latest.isoformat()}_ZERO_COMPANY_MATCHES_"
                    f"RAW_ROWS_{len(normalized_rows)}_ACTIVE_SYMBOLS_{len(active_symbols)}"
                )
            total_added += len(rows)
            if not rows.empty:
                frames.append(rows)
                logger.info("Seeded price history from latest available NSE bhavcopy: %s", latest)
        else:
            failed_dates.append(f"NSE_NO_BHAVCOPY_FOUND_LAST_{settings.nse_latest_scan_days}_DAYS")

    if skipped_dates:
        logger.info("Skipped %s missing/non-trading NSE bhavcopy dates", skipped_dates)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    combined = combined.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    return combined, failed_dates, total_added


def nse_price_diagnostics(company_master: pd.DataFrame) -> dict:
    active_symbols = set(
        company_master[
            company_master["ActiveStatus"].astype(str).str.lower().eq("active")
        ]["NSESymbol"].astype(str).str.strip().str.upper()
    )
    latest = latest_available_bhavcopy_date()
    if not latest:
        return {
            "status": "not_found",
            "scan_days": settings.nse_latest_scan_days,
            "active_symbols": len(active_symbols),
        }
    raw = download_bhavcopy(latest)
    normalized = normalize_bhavcopy(raw, latest)
    matched = filter_active_symbols(normalized, active_symbols)
    sample_symbols = normalized["NSESymbol"].head(10).tolist()
    sample_active = sorted(list(active_symbols))[:10]
    return {
        "status": "found",
        "latest_bhavcopy_date": latest.isoformat(),
        "raw_rows": len(raw),
        "normalized_equity_rows": len(normalized),
        "active_symbols": len(active_symbols),
        "matched_rows": len(matched),
        "sample_bhavcopy_symbols": sample_symbols,
        "sample_active_symbols": sample_active,
    }

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.excel_service import (
    backup_workbook,
    empty_frame,
    load_all_sheets,
    read_sheet,
    utc_now,
    write_workbook,
)
from app.services.nse_price_service import update_price_history_from_nse
from app.services.price_service import update_market_index
from app.services.riskfree_service import update_risk_free_rate
from app.services.universe_service import refresh_company_master
from app.services.validation_service import run_validation_checks
from app.utils.config import settings
from app.utils.logger import get_logger


router = APIRouter()
logger = get_logger(__name__)


def append_log(sheets, task, status, records_added=0, records_updated=0, new_companies=0, failed=None, notes=""):
    failed = failed or []
    log = sheets.get("UPDATE_LOG", empty_frame("UPDATE_LOG"))
    row = {
        "RunTimestamp": utc_now(),
        "Task": task,
        "Status": status,
        "RecordsAdded": records_added,
        "RecordsUpdated": records_updated,
        "NewCompaniesAdded": new_companies,
        "FailedTickers": ", ".join(failed),
        "Notes": notes,
    }
    sheets["UPDATE_LOG"] = log._append(row, ignore_index=True)


def refresh_everything() -> dict:
    backup_workbook()
    sheets = load_all_sheets()
    failed: list[str] = []
    records_added = 0

    company_master, new_listings, delistings, snapshot = refresh_company_master()
    sheets["COMPANY_MASTER"] = company_master
    sheets["UNIVERSE_SNAPSHOT"] = snapshot

    price_history, price_failed, price_added = update_price_history_from_nse(company_master)
    sheets["PRICE_HISTORY"] = price_history
    failed.extend(price_failed)
    records_added += price_added

    market_index, index_failed, index_added = update_market_index()
    sheets["MARKET_INDEX"] = market_index
    failed.extend(index_failed)
    records_added += index_added

    risk_free_rate, risk_rows = update_risk_free_rate()
    sheets["RISK_FREE_RATE"] = risk_free_rate
    records_added += risk_rows

    if sheets.get("ASSUMPTIONS", empty_frame("ASSUMPTIONS")).empty:
        sheets["ASSUMPTIONS"] = default_assumptions()

    checks = run_validation_checks(sheets)
    sheets["DATA_QUALITY_CHECKS"] = checks
    append_log(
        sheets,
        task="refresh-market-data",
        status="SUCCESS_WITH_WARNINGS" if failed else "SUCCESS",
        records_added=records_added,
        new_companies=len(new_listings),
        failed=failed,
        notes=f"Price source: NSE bhavcopy. Inactive/delisted candidates: {len(delistings)}",
    )
    workbook_path = write_workbook(sheets)
    return {
        "status": "success_with_warnings" if failed else "success",
        "workbook": str(workbook_path),
        "records_added": records_added,
        "new_companies_added": len(new_listings),
        "failed_tickers": failed,
        "generated_at": utc_now(),
    }


def default_assumptions():
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "AssumptionName": "MarketDatabaseCurrency",
                "Value": "INR",
                "Source": "System default",
                "Notes": "Used by downstream WACC tooling",
            },
            {
                "AssumptionName": "PrimaryExchange",
                "Value": "NSE",
                "Source": "System default",
                "Notes": "Company universe source",
            },
        ]
    )


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "workbook_exists": settings.workbook_path.exists(),
        "timestamp": utc_now(),
    }


@router.get("/refresh-market-data")
def refresh_market_data():
    try:
        return refresh_everything()
    except Exception as exc:
        logger.exception("Refresh failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/refresh-universe")
def refresh_universe():
    backup_workbook()
    sheets = load_all_sheets()
    master, new_listings, delistings, snapshot = refresh_company_master()
    sheets["COMPANY_MASTER"] = master
    sheets["UNIVERSE_SNAPSHOT"] = snapshot
    append_log(
        sheets,
        task="refresh-universe",
        status="SUCCESS",
        new_companies=len(new_listings),
        notes=f"Inactive/delisted candidates: {len(delistings)}",
    )
    write_workbook(sheets)
    return {
        "status": "success",
        "new_companies_added": len(new_listings),
        "delisting_candidates": len(delistings),
    }


@router.get("/run-validation")
def run_validation():
    sheets = load_all_sheets()
    sheets["DATA_QUALITY_CHECKS"] = run_validation_checks(sheets)
    append_log(sheets, task="run-validation", status="SUCCESS")
    write_workbook(sheets)
    return sheets["DATA_QUALITY_CHECKS"].fillna("").to_dict(orient="records")


@router.get("/latest-update-log")
def latest_update_log(limit: int = 20):
    log = read_sheet("UPDATE_LOG")
    if log.empty:
        return []
    return log.tail(limit).fillna("").to_dict(orient="records")


@router.get("/download-excel")
def download_excel():
    path: Path = settings.workbook_path
    if not path.exists():
        refresh_everything()
    return FileResponse(
        path,
        filename=settings.workbook_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/data/{sheet_name}")
def sheet_data(sheet_name: str):
    normalized = sheet_name.upper()
    if normalized.startswith("PRICE_HISTORY_"):
        normalized = "PRICE_HISTORY"
    allowed = {
        "COMPANY_MASTER",
        "PRICE_HISTORY",
        "MARKET_INDEX",
        "RISK_FREE_RATE",
        "ASSUMPTIONS",
        "UPDATE_LOG",
        "DATA_QUALITY_CHECKS",
        "UNIVERSE_SNAPSHOT",
    }
    if normalized not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown sheet {sheet_name}")
    df = read_sheet(normalized)
    return df.fillna("").to_dict(orient="records")

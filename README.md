# WACC Market Database Backend

This project is a cloud-connected backend for an Excel-based WACC valuation market database. The intended user experience is:

1. Open the Excel workbook.
2. Click **Refresh All**.
3. Power Query calls the backend API.
4. The backend refreshes the NSE company universe, appends missing market prices, updates index and risk-free-rate data, validates the database, regenerates the workbook, and returns refreshed data to Excel.

Users do not install Python, maintain tickers, or manually enter company data.

## Architecture

```text
Excel workbook
  -> Power Query / Office Script refresh
  -> FastAPI cloud backend
  -> NSE + Yahoo Finance market data engine
  -> Append-only Excel database generator
  -> Refreshed Excel sheets
```

## Project Structure

```text
wacc_market_backend/
  app/
    main.py
    api/routes.py
    services/
      universe_service.py
      price_service.py
      excel_service.py
      validation_service.py
      riskfree_service.py
    utils/
      logger.py
      config.py
  data/
    generated_excel/
    backups/
  excel_power_query/
    README.md
  requirements.txt
  Procfile
  runtime.txt
  Dockerfile
  render.yaml
  railway.json
```

## API Endpoints

- `GET /health` - service status.
- `GET /refresh-market-data` - full refresh workflow for Excel.
- `GET /download-excel` - downloads `WACC_MARKET_DATABASE.xlsx`.
- `GET /refresh-universe` - refreshes only the NSE company universe.
- `GET /run-validation` - runs database validation checks.
- `GET /latest-update-log` - returns recent update log rows.
- `GET /data/{sheet_name}` - JSON endpoint for Power Query, for example `/data/COMPANY_MASTER`.

## Generated Workbook Sheets

- `DASHBOARD`
- `COMPANY_MASTER`
- `PRICE_HISTORY`
- `MARKET_INDEX`
- `RISK_FREE_RATE`
- `ASSUMPTIONS`
- `UPDATE_LOG`
- `DATA_QUALITY_CHECKS`
- `UNIVERSE_SNAPSHOT`

If `PRICE_HISTORY` exceeds Excel's row limit, the generated workbook splits it into `PRICE_HISTORY_1`, `PRICE_HISTORY_2`, and so on. The API JSON endpoint still exposes the combined `PRICE_HISTORY` data for Power Query and downstream tools.

## Data Update Logic

- The NSE universe is fetched from NSE's downloadable equity CSV.
- New listings are detected automatically and appended to `COMPANY_MASTER`.
- Delisting candidates are marked inactive when absent from the latest NSE universe.
- Active companies are mapped to Yahoo Finance tickers using `.NS`.
- Daily prices are append-only. Existing historical rows are retained.
- The backend fetches only missing trading days after the latest stored date.
- Exact duplicate `(Date, Ticker)` and `(Date, IndexTicker)` rows are removed.
- One failed ticker does not stop the run. Failed tickers are logged in `UPDATE_LOG`.
- Before each refresh, the prior workbook is backed up as `WACC_MARKET_DATABASE_backup_YYYYMMDD_HHMMSS.xlsx`.

## Local Development

```bash
cd wacc_market_backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/refresh-market-data
http://127.0.0.1:8000/download-excel
```

For quick testing, set `MAX_COMPANY_REFRESH=5` in `.env` so the first run does not download every NSE company.

## Render Deployment

This repo includes `render.yaml`.

1. Push this folder to GitHub, GitLab, or Bitbucket.
2. In Render, create a new Blueprint from the repo.
3. Render reads `render.yaml`.
4. Confirm:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Health check path: `/health`
5. Deploy.

Recommended environment variables:

```text
MAX_COMPANY_REFRESH=0
DEFAULT_HISTORY_YEARS=5
REQUEST_TIMEOUT_SECONDS=30
YAHOO_RETRY_COUNT=2
```

Note: free-tier services may sleep and can time out on very large first refreshes. Use a persistent paid instance for production refreshes of the full NSE universe.

## Railway Deployment

The `railway.json` file sets the start command and health check.

1. Create a Railway project from the repo.
2. Railway uses Nixpacks to install `requirements.txt`.
3. Set the same environment variables listed above.
4. Deploy and test `/health`.

## Azure App Service Deployment

1. Create a Python 3.11 Linux App Service.
2. Deploy this folder.
3. Set startup command from `azure-startup.txt`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4. Add the environment variables listed above.
5. Test `/health`.

## Excel Integration

Use Power Query to connect Excel to the API. Query examples are in:

```text
excel_power_query/README.md
```

Recommended setup:

1. Create a connection-only Power Query named `REFRESH_MARKET_DATABASE` that calls `/refresh-market-data`.
2. Create sheet queries for `COMPANY_MASTER`, `PRICE_HISTORY`, `MARKET_INDEX`, `RISK_FREE_RATE`, and `UPDATE_LOG`.
3. Each sheet query references `REFRESH_MARKET_DATABASE`, forcing the backend refresh before reading data.
4. The user clicks **Data > Refresh All**.

Optional Office Script button:

```typescript
function main(workbook: ExcelScript.Workbook) {
  workbook.refreshAllDataConnections();
}
```

## HTML WACC Tool Integration

The future HTML WACC tool can read either:

- The generated Excel workbook from `/download-excel`.
- JSON sheet data from `/data/COMPANY_MASTER`, `/data/PRICE_HISTORY`, `/data/MARKET_INDEX`, and `/data/RISK_FREE_RATE`.

For large datasets, prefer JSON endpoints or future SQLite/PostgreSQL storage instead of reading a massive `.xlsx` in the browser.

## Production Notes

- NSE and Yahoo Finance endpoints can occasionally throttle or change behavior. The service caches the last successful company universe and logs failed tickers.
- For institutional production, move primary storage to PostgreSQL and generate Excel as an output artifact.
- Keep the append-only price history as the audit trail. Remove exact duplicates only.
- Validate risk-free-rate values before using them in signed valuation reports.


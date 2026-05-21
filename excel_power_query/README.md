# Excel Power Query Setup

Replace `https://your-backend-url.onrender.com` with your deployed API URL.

## Recommended workbook flow

1. Open Excel.
2. Go to Data > Get Data > From Other Sources > Blank Query.
3. Open Advanced Editor.
4. Paste one query per table from the examples below.
5. Set each query to load into a worksheet table.
6. Use Data > Refresh All.

Power Query can call `/refresh-market-data` first, then each sheet query can read the refreshed JSON endpoints.

## Refresh trigger query

Name this query `REFRESH_MARKET_DATABASE`. Set it to connection only.

```powerquery
let
    BaseUrl = "https://your-backend-url.onrender.com",
    Source = Json.Document(Web.Contents(BaseUrl & "/refresh-market-data"))
in
    Source
```

## COMPANY_MASTER

```powerquery
let
    BaseUrl = "https://your-backend-url.onrender.com",
    Refresh = REFRESH_MARKET_DATABASE,
    Source = Json.Document(Web.Contents(BaseUrl & "/data/COMPANY_MASTER")),
    TableData = Table.FromRecords(Source)
in
    TableData
```

## PRICE_HISTORY

```powerquery
let
    BaseUrl = "https://your-backend-url.onrender.com",
    Refresh = REFRESH_MARKET_DATABASE,
    Source = Json.Document(Web.Contents(BaseUrl & "/data/PRICE_HISTORY")),
    TableData = Table.FromRecords(Source)
in
    TableData
```

## MARKET_INDEX

```powerquery
let
    BaseUrl = "https://your-backend-url.onrender.com",
    Refresh = REFRESH_MARKET_DATABASE,
    Source = Json.Document(Web.Contents(BaseUrl & "/data/MARKET_INDEX")),
    TableData = Table.FromRecords(Source)
in
    TableData
```

## RISK_FREE_RATE

```powerquery
let
    BaseUrl = "https://your-backend-url.onrender.com",
    Refresh = REFRESH_MARKET_DATABASE,
    Source = Json.Document(Web.Contents(BaseUrl & "/data/RISK_FREE_RATE")),
    TableData = Table.FromRecords(Source)
in
    TableData
```

## UPDATE_LOG

```powerquery
let
    BaseUrl = "https://your-backend-url.onrender.com",
    Refresh = REFRESH_MARKET_DATABASE,
    Source = Json.Document(Web.Contents(BaseUrl & "/data/UPDATE_LOG")),
    TableData = Table.FromRecords(Source)
in
    TableData
```

## Office Script refresh button

Office Scripts cannot run Python and does not need to. It only tells Excel to refresh the Power Query connections.

```typescript
function main(workbook: ExcelScript.Workbook) {
  workbook.refreshAllDataConnections();
}
```

Add this script to a button in Excel for the web, or use the native Data > Refresh All button in desktop Excel.


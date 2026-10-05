# Flight Tracker & Price Analyzer

航班抓取、過濾、SQLite 歷史追蹤、Web GUI 控制台與 Excel 報表產出系統。詳細規格見 `SPEC.md`。

## 安裝

```bash
pip install -r requirements.txt
playwright install chromium
```

## 使用方式

```bash
# 啟動 Web GUI 控制台（http://localhost:8000）
python src/main.py gui

# CLI 執行 Mock 資料 Pipeline 並匯出 Excel
python src/main.py run --mock --export

# CLI 執行真實 Google Flights 爬蟲並匯出 Excel
python src/main.py run --crawl --export

# 同時使用 Google Flights 與 Skyscanner，限縮航點與自訂時段
python src/main.py run --crawl --sources google_flights,skyscanner --destinations NGO,KIX --window WINDOW_1

# 僅重新匯出 Excel 報表
python src/main.py export
```

## 環境變數

| 變數 | 說明 |
| --- | --- |
| `GEMINI_API_KEY` | Gemini AI 家族旅行顧問功能所需 API Key，未設定時該功能顯示降級提示訊息 |

## 架構重點

- **Scraper 可擴充設計**：`src/scraper/base.py` 定義 `FlightScraper` 抽象介面，`playwright_crawler.py` 提供 Google Flights 實作。未來新增資料來源（如 Skyscanner）只需新增同介面子類別，不需更動 pipeline 或 API 層。
- **嚴格時間過濾**：`src/pipeline/filter_engine.py` 依 SPEC 2.3 規則為每筆航班附加 `passes_strict_rule` 旗標，供 GUI 動態開關過濾條件，而非直接刪除資料。
- **去重機制**：`snapshot_hash = MD5(flight_date + flight_number + price_twd)`，透過 SQLite `UNIQUE` 約束與 `INSERT OR IGNORE` 防止重複寫入。

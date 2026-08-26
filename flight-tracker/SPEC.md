# **Flight Tracker & Price Analyzer GUI \- Technical Specification**

## **1\. Project Overview & Objective**

本專案為輕量級的**航班資訊抓取、過濾、SQLite 歷史追蹤、Web GUI 控制台與 Excel 報表產出系統**。

主要用於追蹤 2027 年特定出發區間內，台北 (TPE/TSA) 出發至 6 個目標航點（NGO, KIX, SDJ, CTS, HIJ, PUS）的航班票價與時刻，並依照業務邏輯過濾，最後儲存至本地 SQLite，透過雙介面（CLI \+ Web GUI）進行直觀比價與分析。

* **開發語言與環境**：Python 3.10+  
* **Web 後端框架**：FastAPI / Uvicorn（提供 REST API 與 SSE 即時日誌串流）  
* **Web 前端 GUI**：單一 HTML 檔案 (index.html)，搭配 Tailwind CSS、Chart.js 與 FontAwesome  
* **儲存機制**：SQLite (data/flight\_tracker.db) \+ Pandas / OpenPyXL  
* **資料抓取機制**：Playwright (支援 Headless 模式與 XHR/Network Interception)

## **2\. Business Rules & Filter Constraints**

### **2.1 目標航點 (Destinations)**

* 目的地 IATA 代碼：NGO (名古屋)、KIX (大阪)、SDJ (仙台)、CTS (札幌/北海道)、HIJ (廣島)、PUS (釜山)  
* 出發地 IATA 代碼：TPE 或 TSA

### **2.2 出發與回程日期區間 (Target Dates)**

* **時段 1**：  
  * 去程：2027-07-11 (週日)  
  * 回程：2027-07-17 (週六) 或 2027-07-18 (週日)  
* **時段 2**：  
  * 去程：2027-08-15 (週日)  
  * 回程：2027-08-21 (週六) 或 2027-08-22 (週日)

### **2.3 航班時刻硬性過濾條件 (Strict Time Rules)**

* **去程限制（週日）**：出發地當地起飛時間必須 **\< 15:00**。  
* **回程限制（依星期別）**：  
  * 若為**週六回程**：當地起飛時間必須 **\< 20:00**。  
  * 若為**週日回程**：當地起飛時間必須 **\< 14:00**。

## **3\. Architecture & Project Structure**

flight-tracker/  
├── config/  
│   └── settings.yaml          \# 航點、目標日期、過濾規則、匯率等設定  
├── src/  
│   ├── scraper/  
│   │   ├── base.py            \# Scraper 抽象介面  
│   │   └── playwright\_crawler.py \# Playwright XHR 攔截/爬蟲實作  
│   ├── pipeline/  
│   │   ├── normalizer.py      \# 資料清洗、時區轉換、匯率換算  
│   │   └── filter\_engine.py   \# 時段/星期過濾規則引擎  
│   ├── db/  
│   │   ├── database.py        \# SQLite 連線與 Session 管理  
│   │   └── models.py          \# SQLite Schema (SQLAlchemy or raw sqlite3)  
│   ├── exporter/  
│   │   └── excel\_exporter.py  \# 格式化 Excel 產出模組  
│   ├── api/  
│   │   └── server.py          \# FastAPI 伺服器與 REST/SSE 端點  
│   └── main.py                \# CLI 入口與 GUI Web Server 啟動器  
├── web/  
│   └── index.html             \# 單一頁面 Web GUI 介面  
├── data/  
│   ├── flight\_tracker.db      \# SQLite 資料庫檔案  
│   └── reports/               \# 產出的 Excel 比價表  
├── requirements.txt  
├── SPEC.md  
└── README.md

## **4\. Web GUI & API Specification**

### **4.1 GUI 控制台頁面 (web/index.html) 功能區塊**

1. **主控台與爬蟲任務 (Control Center)**：  
   * 選擇執行模式：--mock（測試資料）或 \--crawl（真實 Playwright 爬蟲）。  
   * 勾選目標航點與旅遊時段。  
   * **Terminal Console**：顯示即時管道執行 Log 串流。  
2. **航班時刻與過濾 (Strict Filter Engine)**：  
   * 動態切換硬性過濾規則（開啟/關閉）。  
   * 提供多維度篩選：目的地、行程類型（去程/回程）、時段與價格排序。  
3. **Phase 1 航點橫向評比 (Phase 1 Matrix)**：  
   * 顯示 6 大航點之直飛班次匹配度、住宿成本與地面交通分析。  
   * Chart.js 橫向堆疊圖表呈現預估每人總開銷。  
4. **SQLite 數據庫檢視 (DB Inspector)**：  
   * 呈現 flight\_price\_snapshots 全數資料列。  
   * 提供「測試 Hash 去重 (INSERT OR IGNORE)」與關鍵字搜尋。  
5. **AI 家族旅行顧問 (Gemini AI Advisor)**：  
   * 對接 Gemini API (gemini-3-flash-preview)，解答家族行程預算與景點問題。

### **4.2 FastAPI 後端 API 路由規格 (src/api/server.py)**

* GET /：提供 web/index.html 靜態 GUI 介面。  
* GET /api/status：取得當前 SQLite 資料庫總筆數與系統連線狀態。  
* POST /api/run-pipeline：觸發爬蟲或 Mock Pipeline，透過 SSE (text/event-stream) 即時推播進度日誌至前端 Terminal。  
* GET /api/flights：查詢合格航班列表（支援航點、日期與過濾條件參數）。  
* GET /api/db/snapshots：取得 SQLite 所有原始快照資料。  
* GET /api/export/excel：即時產生並下載 Excel 比價報表檔案 (.xlsx 或 .csv)。  
* POST /api/ai/chat：Proxy 呼叫 Gemini AI 服務（若前端未帶入 Key，由後端環境變數提供）。

## **5\. Database Schema (SQLite)**

### **Table: flight\_price\_snapshots**

記錄每次抓取到的合格航班價格快照與歷史記錄。

| 欄位名稱 | 型態 | 說明 / 約束 |
| :---- | :---- | :---- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| flight\_date | TEXT | 飛行日期 (YYYY-MM-DD)，NOT NULL |
| trip\_type | TEXT | 行程類型 (OUTBOUND 去程 / INBOUND 回程) |
| origin\_airport | TEXT | 出發機場代碼 (如 TPE)，NOT NULL |
| dest\_airport | TEXT | 抵達機場代碼 (如 NGO)，NOT NULL |
| airline\_code | TEXT | 航空公司代碼 (如 CI, BR, CX, JX) |
| flight\_number | TEXT | 航班號碼 (如 CI154)，NOT NULL |
| departure\_time | TEXT | 當地出發時刻 (HH:mm)，NOT NULL |
| arrival\_time | TEXT | 當地抵達時刻 (HH:mm)，NOT NULL |
| price\_twd | INTEGER | 折合新台幣總票價 (含基本行李稅費) |
| original\_currency | TEXT | 原始抓取幣別 (如 JPY, KRW, TWD) |
| original\_price | REAL | 原始幣別價格 |
| snapshot\_hash | TEXT | **UNIQUE** (MD5(flight\_date \+ flight\_number \+ price\_twd)) |
| captured\_at | TIMESTAMP | 抓取時間，DEFAULT CURRENT\_TIMESTAMP |

## **6\. CLI & Web Server Execution Commands**

請實作 src/main.py 支援以下指令：

1. **啟動 GUI Web Dashboard** (預設開啟 http://localhost:8000)：  
   python src/main.py gui

2. **純 CLI 執行抓取與匯出**：  
   python src/main.py run \--crawl \--export

3. **純 CLI 模擬載入 Mock 資料**：  
   python src/main.py run \--mock \--export

4. **僅重新匯出 Excel 報表**：  
   python src/main.py export

## **7\. Acceptance Criteria (驗收條件)**

1. 執行 python src/main.py gui 後，打開瀏覽器能載入完整的 Web 控制台。  
2. 在 GUI 點擊「執行 Task」能透由 Server-Sent Events (SSE) 即時在網頁 Console Terminal 印出爬蟲處理 Log。  
3. 於 GUI 點擊「匯出 Excel 報表」能順利下載格式美化的 .xlsx 或 .csv 報表。  
4. 資料庫去重邏輯正常（使用 INSERT OR IGNORE 確保相同 Hash 快照不重複寫入）。  
5. 嚴格遵守去程（週日 \< 15:00）與回程（週六 \< 20:00 / 週日 \< 14:00）的時間過濾邏輯。
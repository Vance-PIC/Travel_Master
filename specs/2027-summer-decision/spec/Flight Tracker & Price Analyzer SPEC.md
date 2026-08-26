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
* **行程天數彈性規則**：每筆時程是一組完整的「去程截止日期時間 (`outbound_before`) ＋ 回程截止日期時間 (`inbound_before`)」。2027 年 7 月與 8 月各建立週六、週日回程兩筆，共四筆時程；系統比較同一月份群組內的候選時程，再決定各地區最佳回程星期與行程天數。
* **最佳回程判定**：先排除不符合上述時間限制的配對，再依來回總價由低到高選擇；同價時優先選週日回程（保留較長行程），其後依回程當地出發時間由晚到早排序。先選出同航空公司的最佳候選，再跨航空公司選出每個「地區 × 月份群組」唯一的整體最佳方案。原始不合格航班仍保留於資料庫供查核，但不得標記為推薦方案。

## **3\. Architecture & Project Structure**

flight-tracker/  
├── config/  
│   └── settings.yaml          \# 航點、時段、航空公司對照表（含廉航旗標）、嚴格時間規則、匯率、DB/報表路徑、爬蟲參數等設定  
├── src/  
│   ├── config.py               \# settings.yaml 讀寫工具（含 lru\_cache 快取、db\_path()/reports\_dir() 輔助函式）  
│   ├── scraper/  
│   │   ├── base.py            \# Scraper 抽象介面 (FlightScraper ABC，`source_name` 標識來源)  
│   │   ├── playwright\_crawler.py \# Google Flights Playwright XHR 攔截/爬蟲實作 (`source_name = "google_flights"`)  
│   │   └── skyscanner\_crawler.py \# Skyscanner Playwright 爬蟲實作 (`source_name = "skyscanner"`) — **原規格未定義**  
│   ├── mock/  
│   │   └── mock\_data.py       \# Mock 模式測試資料產生器  
│   ├── pipeline/  
│   │   ├── normalizer.py      \# 資料清洗、時區轉換、匯率換算  
│   │   ├── filter\_engine.py   \# 時段/星期過濾規則引擎 \+ 航空公司名稱正規化/廉航判定  
│   │   ├── schedule\_builder.py \# 去回程航班配對，組成航班時刻表列（詳見 4.1.2）  
│   │   └── runner.py          \# 兩階段 Pipeline（航班發現 → 票價/資訊補充 → FilterEngine → DB → Excel），以 generator yield 進度事件  
│   ├── db/  
│   │   ├── database.py        \# SQLite 連線與 Session 管理  
│   │   └── models.py          \# SQLite Schema (raw sqlite3 \+ dataclass)  
│   ├── exporter/  
│   │   └── excel\_exporter.py  \# 格式化 Excel (.xlsx) 產出模組  
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

實際共 6 個分頁（Tab）：主控台、航班時刻與過濾、Phase 1 航點評比、SQLite 數據庫、AI 家族旅行顧問、設定。

#### **4.1.1 全站資訊架構與視覺規範**

* 採深色決策儀表板風格，內容區設最大寬度並置中，避免寬螢幕表格與圖表無限制拉伸；頂部導覽與系統狀態列在捲動時保持可見。
* 每個分頁須有明確頁面標題、用途說明與主要動作；一般操作、查核資料及開發工具須形成清楚層級，Debug／Hash 測試等開發功能不得搶占主要視覺焦點。
* 主控台依操作順序呈現「選擇航點 → 查詢條件 → 開始查詢」，目標航點使用可辨識選取狀態的按鈕卡；Debug Mock 收於「進階／開發設定」。Terminal Console 預設可收合，執行時自動展開，並在上方顯示階段與百分比。
* 「航班時刻與過濾」先呈現決策用途的已配對票價，再以可收合區塊呈現 Stage 1 原始航班。整體最佳與航空最佳須有不同視覺標記；空值一律顯示 `—`，不得在畫面出現 `undefined`／`null`。
* 表格採固定表頭、適度列高、數字靠右與橫向捲動；破壞性動作採紅色並與一般動作分離。設定頁保留高密度編輯能力，但新增資料區與既有資料列須有明確分隔。
* 設定頁採卡片式編輯：地區卡顯示 IATA、名稱與排序；時段卡將同一筆去程截止與回程截止並列，直接顯示回程星期；航空公司卡顯示代碼、名稱與是否納入查詢。各子頁的新增表單獨立放在既有項目下方，儲存列固定於內容底部並顯示儲存狀態。
* 介面需支援桌面與窄螢幕：控制項可自動換行，主要操作按鈕在窄螢幕保持可見，不得依賴固定畫面寬度。

1. **主控台與爬蟲任務 (Control Center)**：  
   * 一般操作固定執行真實 Playwright 流程，不提供 Mock／真實二選一。僅保留明確標示的「Debug（使用 Mock 資料）」開關；預設關閉，只有開啟時前端才送出 `mode: "mock"`，否則固定送出 `mode: "crawl"`。  
   * 勾選目標航點與旅遊時段。  
   * 設定旅客人數（`passenger_count`，整數且至少 1）與是否僅查直達航班（`direct_only`，預設 true）；兩者必須同時套用於航班發現與後續查價。  
   * Pipeline 分成「① 發現航班」與「② 補充票價」兩個明確階段；可個別執行，也可依序執行全部。  
   * 航班發現固定以 Google Flights 為主要來源；票價補充可選 Google Flights／Skyscanner／人工匯入或未來正式 API。  
   * **Terminal Console**：顯示即時管道執行 Log 串流與進度百分比，多來源爬蟲時每行 Log 前綴 `[來源名稱]` 標示資料來源 — **原規格未定義**。  
2. **航班時刻與過濾 (Strict Filter Engine \+ Schedule Matrix)**：  
   * 動態切換硬性過濾規則（開啟/關閉）。  
   * 提供多維度篩選：目的地、時段（window）、查價旅客人數；旅客人數與主控台同步並記住瀏覽器上次選擇，避免資料庫已有多人票價卻因預設 1 人而顯示無配對。  
   * 呈現的是 `schedule_builder.py` 配對後的**航班時刻表**（去回程同航空公司配對列），而非單段原始快照列表，詳見 4.1.2。  
3. **Phase 1 航點橫向評比 (Phase 1 Matrix)**：  
   * 顯示 6 大航點之直飛班次匹配度、住宿成本與地面交通分析。  
   * Chart.js 橫向堆疊圖表呈現預估每人總開銷。  
4. **SQLite 數據庫檢視 (DB Inspector)**：  
   * 同時呈現 `flight_price_snapshots` 單程初估與 `roundtrip_price_snapshots` 正式來回資料；兩種類型不得共用錯誤欄位語意。正式來回列須分別顯示去程／回程日期、航班號、出發與抵達時間，航段使用 `↔`；單程列使用 `→` 並只顯示單一航段。  
   * 每列須顯示旅客人數、艙等、來源與價格性質；正式來回票價標示為所有旅客總額並提供每人均價，單程則標示初估價。`last_checked_at` 在 SQLite 保留 UTC，GUI 必須轉換為 `Asia/Taipei` 並明確標示台北時間。
   * 提供「測試 Hash 去重」與關鍵字搜尋。  
   * 提供「清除票價快照」與「清除全部資料」兩個動作；前者只清空單程初估與正式來回票價快照，後者須二次確認後一併清除已確認航班實例 — **原規格未定義**。  
5. **AI 家族旅行顧問 (Gemini AI Advisor)**：  
   * 對接 Gemini API (gemini-3-flash-preview)，解答家族行程預算與景點問題。  
6. **設定 (Settings) — 原規格未定義，實作新增之管理頁面**：  
   * 三個子分頁：地區（目的地）、時段（去程/候選回程日期）、航空公司（含「是否查詢」勾選，對應 `is_lcc` 反向邏輯／廉航排除）。  
   * 可新增/編輯後透過 `POST /api/settings` 寫回 `config/settings.yaml`（覆寫 `origins`/`destinations`/`windows`/`airlines`，不影響 `strict_time_rules`/`exchange_rates`/`database`/`reports`/`scraper` 區塊）。
   * 「時段」子分頁以卡片維護完整時程，每筆包含：群組、標籤、查詢順序、去程截止日期時間、回程截止日期時間。預設共四筆：7 月週六、7 月週日、8 月週六、8 月週日。
   * `query_order` 為大於等於 1 的整數，可由設定頁直接維護；Pipeline 查詢工作、主控台／篩選下拉選單、時段卡片與結果排序均依 `query_order` 由小到大排列。相同順序值依 `settings.yaml` 原始宣告順序保持穩定排序；舊設定缺少此欄位時，依原始順序自動補為 1、2、3……。
   * 去程與回程均使用單一 `input[type=datetime-local]`，不得拆成日期欄與時間欄；例如 `2027-07-11T15:00` 表示 2027-07-11 當地時間 15:00 前出發。截止時間語意一律為嚴格小於，星期由回程日期自動顯示。
   * 同群組（例如 `JULY_2027`）的多列視為可互相比較的回程候選；最佳方案依 2.3 規則選出。
   * 每張時程卡提供「複製設定」功能：將該卡的群組、標籤及去／回程截止日期時間帶入下方「新增時程」表單，但**不自動新增卡片、不自動產生 `_COPY` 代碼**；代碼欄保持空白並取得焦點，由使用者自行輸入有意義且唯一的代碼後按「新增時程」。
   * 時程代碼可直接重新命名；提交時去除前後空白並轉為大寫。新代碼不得為空、不得與其他時程重複；驗證失敗時保留原代碼並顯示錯誤，不得覆寫既有時程。重新命名須保留該卡的排序、群組、標籤及去／回程日期時間，仍須按「儲存全部設定」才寫入 `settings.yaml`。

### **4.1.2 航班時刻表配對邏輯 (schedule\_builder.py) — 原規格未定義**

* 輸入須為 `annotate_flights()` 處理過（含 `passes_strict_rule`／`airline_name`／`is_lcc`）之航班清單。  
* **先排除廉航**：`is_lcc = true` 之航空公司不參與配對（依 `config/settings.yaml` 之 `airlines[].is_lcc`）。  
* 配對前先依「航班實例（舊資料則以日期、航段、航班號識別）× 來源 × 艙等 × 旅客人數」保留最後觀測時間最新的價格；不得直接使用該航班歷史最低價。最後觀測時間以 `last_checked_at` 為準，缺值時依序回退至 `captured_at`、資料列 `id`。
* 同一航班在各來源的最新價格分別保留；進入配對時，在相同艙等與旅客人數的條件下選擇各段「最新來源價格中的最低價」，並顯示實際採用的來源。不同旅客人數或艙等不得混合組成同一來回配對。
* 依「地區 ✕ 時段（含每個候選回程日期）」分組，僅組成**去程與回程皆有出現該航空公司**的配對列（該公司符合上述規則的去程最低價 \+ 回程最低價）。  
* 每列輸出：地區、時段、回程星期、行程天數（去程至回程含首尾天數）、旅客人數、艙等、去/回程航空公司、航班號、時刻（含日期）與價格來源、來回總價 (TWD)、`is_airline_best`、`is_recommended`、備註。原始不合格配對可供查核，但兩種最佳旗標必須為 false。  
* 每個「地區 × 月份群組 × 航空公司 × 艙等 × 旅客人數」依 2.3 規則最多選出一列 `is_airline_best=true`；再由各航空公司最佳候選中，以相同排序規則選出每個「地區 × 月份群組 × 艙等 × 旅客人數」唯一一列 `is_recommended=true`。
* 排序：依地區設定順序 → 時段 `query_order` → 來回總價由低到高。

### **4.1.3 兩階段航班發現與資訊補充流程 (runner.py)**

#### **Stage 1：航班發現 (DISCOVER)**

* 以 Google Flights 依「出發機場 × 航點 × 日期」搜尋候選航班，目標是先確認航班身分與時刻，不以票價作為航班唯一識別。
* Google Flights 查詢前須在本地以台北當日日期檢查目標日期；若超過 `config/settings.yaml` 的 `scraper.google_flights_max_advance_days`（預設 330 天），該航段直接標記為「日期超出 Google Flights 可查詢範圍，已跳過」，不得啟動 Playwright、開啟頁面或送出網路請求。此限制只套用 Google Flights，不得阻止其他具有不同日期範圍的來源。
* 基礎搜尋 URL 僅承載航段、日期與單程條件；旅客人數須在結果頁透過 Google Flights 的乘客控制項設定，避免自然語句未被 Google 解析而退回探索首頁。`direct_only=true` 由解析結果的 `stops=0` 在本地強制過濾，轉機航班不得寫入正式航班清單。
* 結果卡若未直接顯示航班號，crawler 必須展開航班詳情後擷取航空公司、行銷航班號、出發/抵達時間、直飛/轉機資訊與可取得的航機資料。
* 只有取得格式有效的真實航班號（例如 `BR108`）才可寫入 `flight_instances`；`UNKNOWN`、空字串或無法對應航段的結果不得寫入正式航班清單，僅記錄 warning。
* 航班實例依 `flight_date + flight_number + origin_airport + dest_airport` 去重；再次發現相同航班時更新 `last_verified_at`，不得建立重複航班。
* Google Flights 在發現階段同時顯示的價格可暫存於記憶體，但必須等航班號確認並建立 `flight_instance_id` 後，才可進入 Stage 2 寫入價格快照。
* Stage 1 固定使用單程搜尋以穩定取得個別航班號與時刻；其單程價格只可標示為「初步估價」，不得用於最終來回推薦。

#### **Stage 2：票價與其他資訊補充 (ENRICH)**

* Stage 2 必須從資料庫的已確認航班建立候選組合，不得把兩張單程價格相加當作最終票價。每個「目的地 × 完整時程 × 航空公司」先依嚴格時間規則篩選，再各取最多 `scraper.roundtrip_candidate_limit_per_airline` 班去程及回程（預設各 2 班）以限制查詢量。
* 完整 `all` Pipeline 在 Stage 1 後進入 Stage 2 時，只能使用本次執行剛確認／重新確認的航班實例；不得因歷史 `flight_instances` 尚未刪除而把未出現在本次結果的舊航班加入候選。單獨執行 `enrich` 階段時，才讀取資料庫既有航班實例供使用者手動補查。
* 候選去程與回程必須屬於同一家航空公司；Google Flights 顯示的跨航空公司組合可保留於原始頁面，但不得寫入正式來回快照或標記為推薦。
* Google Flights 查價必須使用真正的來回搜尋，攜帶出發地、目的地、去程日期、回程日期、艙等、旅客人數與直達條件；去程清單應在控制項可用時切換為「依出發時間排序」，再選定候選去程並解析可搭配的回程航班及 Google 顯示的完整來回總價。排序只用於穩定定位，不得取代航班號核對。
* Google Flights 的 `data-travelimpactmodelwebsiteurl` 為航班識別 metadata，可能存在於不可見的子元素；Playwright 必須等待該元素 `state="attached"`，不得以預設 `visible` 判定結果是否載入。此 metadata 在去程清單亦可能重複或錯標為其他航班；無法以 metadata 命中候選去程時，必須以 Stage 1 已確認的出發／抵達時刻定位卡片，再展開航班詳細資料核對完整航班號，確認一致後才可選取。不得僅因 metadata 未命中就宣告候選航班不存在。選取去程後若 DOM 確實沒有任何回程 metadata，應記錄「未出現可選回程」並略過，不得將正常無組合狀態混同為通用解析錯誤。
* 一筆正式來回票價須同時對應已確認的 `outbound_flight_instance_id` 與 `inbound_flight_instance_id`。只有兩個航班號都能對應候選實例時才可寫入 `roundtrip_price_snapshots`；無法確認任一航段時僅記錄 warning。
* 票價來源可為 Google Flights、人工 Web Search 匯入或未來正式 API；每筆快照必須保存 `source`、旅客人數、艙等與最後觀測時間。既有 `flight_price_snapshots` 保留作為單程歷史／初步估價，但不再作為最終推薦資料源。
* Skyscanner Playwright 若被導向 CAPTCHA，須立即將該來源標記為本次 Pipeline 不可用、只警告一次並繼續其他來源；不得嘗試繞過 CAPTCHA。
* 單一來源查詢失敗不得刪除已發現的航班，也不得中斷其他航班或來源。
* 「其他資訊」包含可取得的航機型號、飛行時間、直飛/轉機、營運航空公司與來源連結；查不到的欄位保留 NULL，不得臆測。
* Debug／Mock 模式的 `discover`、`enrich`、`all` 三種階段均不得啟動真實 crawler、Playwright 或任何外部查價請求；Mock 正式來回票價只能由明確標記的 Mock fixture 產生。
* SSE 百分比在同一次 Pipeline 內只能維持或增加，不得因切換子階段而倒退。

#### **Stage 3：分析與配對 (ANALYZE)**

* 嚴格時間規則以 `flight_instances` 的時刻判定。
* 航班時刻表可顯示尚無正式來回票價的已確認航班；最終「航空最佳／整體最佳」只能使用 `roundtrip_price_snapshots` 的實際完整來回總價。
* 多來源同一來回組合的價格須分別保存；分析時先取各來源最後觀測價，再由有效候選依價格、行程長度與回程時間選出推薦。歷史低價與單程加總僅供趨勢查核，不得當作目前推薦票價。

### **4.2 FastAPI 後端 API 路由規格 (src/api/server.py)**

* GET /：提供 web/index.html 靜態 GUI 介面。  
* GET /api/status：取得當前 SQLite 資料庫總筆數與系統連線狀態。  
* POST /api/run-pipeline：觸發 Mock 或兩階段 Pipeline，透過 SSE 即時推播進度；支援 `stage: "discover" | "enrich" | "all"`（預設 `all`）、`passenger_count: int`（預設 1）、`direct_only: bool`（預設 true）及 Stage 2 使用的 `sources: list[str]`。  
* GET /api/flight-instances：查詢已確認航班號的航班實例，支援 dest／trip\_type／window／strict／has\_price 參數。  
* POST /api/flight-instances/{id}/enrichment：匯入人工 Web Search 或外部 API 查得的票價及其他資訊，需驗證航班實例存在。  
* GET /api/flights：查詢合格航班列表（支援 dest／trip\_type／window／strict 參數，回傳附加 `passes_strict_rule`／`airline_name`／`is_lcc` 之航班清單）。  
* GET /api/flight-schedule：查詢 `schedule_builder.py` 配對後之航班時刻表（支援 dest／window／passenger\_count／cabin\_class 參數）；GUI 預設帶入主控台目前的旅客人數 — **原規格未定義**。  
* GET /api/settings：取得目前 `origins`／`destinations`／`windows`／`airlines`／`strict_time_rules` 設定 — **原規格未定義**。  
* POST /api/settings：更新並寫回 `origins`／`destinations`／`windows`／`airlines`／`strict_time_rules` 設定至 settings.yaml；其他設定區塊不得被覆寫 — **原規格未定義**。  
* SQLite 檢視、資料清除與 Excel 匯出須明確涵蓋 `flight_price_snapshots` 與 `roundtrip_price_snapshots`；不得讓正式來回票價只能寫入、無法檢視或管理。
* SQLite 檢視亦須提供 `flight_instances` 航班實例清單；已確認但尚無任何價格快照的航班仍要可搜尋，並標示單程／正式來回價格是否存在。
* GUI 必須區分「清除票價快照」（只刪除單程初估與正式來回價格，保留航班實例）與「清除全部航班資料」（依正式來回、單程初估、航班實例順序全部刪除）；後者須有明確的二次確認。
* GET /api/db/snapshots：取得 SQLite 所有原始快照資料。  
* DELETE /api/db/snapshots：清空 `flight_price_snapshots` 與 `roundtrip_price_snapshots` 全部資料列，保留 `flight_instances`，回傳 `{"deleted": <筆數>, "details": {...}}` — **原規格未定義**。  
* DELETE /api/db/all：清空 `roundtrip_price_snapshots`、`flight_price_snapshots` 與 `flight_instances` 全部資料列，回傳 `{"deleted": <筆數>, "details": {...}}` — **原規格未定義**。  
* GET /api/export/excel：即時產生並下載 Excel 比價報表檔案（僅 **.xlsx**，未提供 .csv 格式）。  
* POST /api/ai/chat：Proxy 呼叫 Gemini AI 服務（若後端環境變數 `GEMINI_API_KEY` 未設定，回傳降級提示訊息 `degraded: true` 而非 500 錯誤）。

## **5\. Database Schema (SQLite)**

### **Table: flight\_instances**

保存 Stage 1 已確認航班號的航班實例；航班時刻與票價歷史分離。

| 欄位名稱 | 型態 | 說明 / 約束 |
| :---- | :---- | :---- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| flight\_date | TEXT | 飛行日期，NOT NULL |
| trip\_type | TEXT | OUTBOUND / INBOUND，NOT NULL |
| origin\_airport | TEXT | 出發機場，NOT NULL |
| dest\_airport | TEXT | 抵達機場，NOT NULL |
| airline\_code | TEXT | 行銷航空公司代碼 |
| operating\_airline | TEXT | 實際營運航空公司，可為 NULL |
| flight\_number | TEXT | 已確認航班號，NOT NULL；不得為 UNKNOWN |
| departure\_time | TEXT | 當地出發時間，NOT NULL |
| arrival\_time | TEXT | 當地抵達時間，NOT NULL |
| duration\_minutes | INTEGER | 飛行時間，可為 NULL |
| stops | INTEGER | 0 代表直飛，可為 NULL |
| aircraft\_type | TEXT | 航機型號，可為 NULL |
| discovery\_source | TEXT | 航班發現來源，預設 google\_flights |
| source\_url | TEXT | 查詢或佐證網址，可為 NULL |
| discovered\_at | TIMESTAMP | 首次發現時間 |
| last\_verified\_at | TIMESTAMP | 最後確認仍存在的時間 |

唯一約束：`UNIQUE(flight_date, flight_number, origin_airport, dest_airport)`。

### **Table: flight\_price\_snapshots**

記錄 Stage 2 對已確認航班的價格觀測；既有欄位保留以相容舊資料。

| 欄位名稱 | 型態 | 說明 / 約束 |
| :---- | :---- | :---- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| flight\_instance\_id | INTEGER | FK → flight\_instances.id；新流程寫入時 NOT NULL |
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
| source | TEXT | google\_flights / skyscanner / manual / 其他 API |
| cabin\_class | TEXT | 艙等，預設 ECONOMY |
| passenger\_count | INTEGER | 查價人數，預設 1 |
| baggage\_description | TEXT | 行李條件，可為 NULL |
| source\_url | TEXT | 價格來源網址，可為 NULL |
| snapshot\_hash | TEXT | **UNIQUE** (MD5(flight\_instance\_id + source + 查詢條件 + price\_twd)) |
| captured\_at | TIMESTAMP | 首次抓取時間，DEFAULT CURRENT\_TIMESTAMP（同一 hash 重複寫入不更新此欄） |
| last\_checked\_at | TIMESTAMP | 最後一次查詢到相同快照（同 hash）的時間，DEFAULT CURRENT\_TIMESTAMP，每次重複命中即更新 — **原規格未定義** |

### **Table: roundtrip\_price\_snapshots**

記錄 Stage 2 真正的來回搜尋價格；此表是最終推薦與航點評比的正式機票價格來源。

| 欄位名稱 | 型態 | 說明 / 約束 |
| :---- | :---- | :---- |
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| outbound\_flight\_instance\_id | INTEGER | FK → flight\_instances.id，NOT NULL |
| inbound\_flight\_instance\_id | INTEGER | FK → flight\_instances.id，NOT NULL |
| window\_key | TEXT | 對應完整旅行時程代碼，NOT NULL |
| source | TEXT | google\_flights / manual / 其他 API |
| cabin\_class | TEXT | 艙等，預設 ECONOMY |
| passenger\_count | INTEGER | 查價人數，NOT NULL |
| price\_twd | INTEGER | Google Flights 顯示的完整來回總價，NOT NULL；不得由單程相加產生 |
| original\_currency | TEXT | 原始幣別 |
| original\_price | REAL | 原始完整來回價格 |
| source\_url | TEXT | 來回搜尋或佐證網址 |
| snapshot\_hash | TEXT | UNIQUE (MD5(時程代碼 + 去程實例 + 回程實例 + source + 艙等 + 人數 + price)) |
| captured\_at | TIMESTAMP | 首次觀測時間 |
| last\_checked\_at | TIMESTAMP | 最後一次觀測到相同價格的時間；重複 hash 更新此欄 |

唯一來回組合身分由去程實例、回程實例與查價條件共同決定；不同價格保留歷史快照。

## **6\. CLI & Web Server Execution Commands**

src/main.py 實際支援以下指令：

1. **啟動 GUI Web Dashboard** (預設開啟 http://localhost:8000)：  
   python src/main.py gui \[--port 8000\] \[--no-browser\]

2. **純 CLI 執行抓取與匯出**：  
   python src/main.py run \--crawl \[--export\] \[--window ALL|WINDOW\_1|WINDOW\_2\] \[--destinations NGO,KIX\]

3. **純 CLI 模擬載入 Mock 資料**：  
   python src/main.py run \--mock \[--export\] \[--window ALL|WINDOW\_1|WINDOW\_2\] \[--destinations NGO,KIX\]

4. **僅重新匯出 Excel 報表**（讀取現有 DB 資料，若無資料則印出提示訊息而不產生檔案）：  
   python src/main.py export

備註：`--mock` 與 `--crawl` 為互斥必選其一（argparse mutually\_exclusive\_group required=True）；`--window`／`--destinations` 為原規格未定義之新增參數，用以限縮 Pipeline 執行範圍。

## **7\. Acceptance Criteria (驗收條件)**

1. 執行 python src/main.py gui 後，打開瀏覽器能載入完整的 Web 控制台（含設定管理分頁）。  
2. 在 GUI 點擊「執行 Task」能透由 Server-Sent Events (SSE) 即時在網頁 Console Terminal 印出爬蟲處理 Log 與百分比進度。  
3. 於 GUI 點擊「匯出 Excel 報表」能順利下載格式美化的 **.xlsx** 報表（不含 .csv 格式）。  
4. 資料庫去重邏輯正常（依 snapshot\_hash 確保相同快照不重複新增；重複命中時更新 `last_checked_at` 而非新增資料列，藉此得知每筆票價最後查詢時間）。  
5. 嚴格遵守去程（週日 \< 15:00）與回程（週六 \< 20:00 / 週日 \< 14:00）的時間過濾邏輯，且過濾結果以 `passes_strict_rule` 旗標附加而非刪除原始資料。  
6. 「航班時刻與過濾」分頁能正確呈現去回程同航空公司配對後之來回總價列表，且已排除廉航（`is_lcc=true`）航班。  
7. 「設定」分頁可新增/編輯地區、時段、航空公司資料，儲存後 `config/settings.yaml` 隨之更新且立即生效（無需重啟服務）。
8. Stage 1 必須能展開 Google Flights 結果並取得真實航班號；任何 `UNKNOWN` 航班不得寫入 `flight_instances`。  
9. Stage 1 重複執行時，相同航班實例只更新 `last_verified_at`；Stage 2 的不同來源價格則分別保留。  
10. Stage 2 失敗或來源被 CAPTCHA 阻擋時，已發現航班仍可在 GUI 顯示，Pipeline 其餘工作繼續執行。  
11. GUI 與 SSE 日誌需明確標示 DISCOVER／ENRICH／ANALYZE 階段、已確認航班數、無航班號略過數及成功新增價格數。
12. Google Flights 查詢須依 GUI 設定帶入旅客人數與直達條件；`direct_only=true` 時資料庫不得新增轉機航班，價格快照的 `passenger_count` 必須與查詢人數一致。
13. Google Flights 若未解析搜尋條件而停留在探索首頁，crawler 必須回報明確 warning，不得等待結果卡 selector 至逾時才只回報通用 Timeout。
14. 每個地區與時段須同時評估週六、週日回程；推薦方案必須符合各自星期的時間限制，先選各航空公司最佳，再跨航空公司依價格、行程長度與回程時間規則選出每個地區、月份群組、艙等與旅客人數唯一的整體最佳候選；GUI 顯示實際回程星期及行程天數。
15. 已配對票價只能使用每個航班、來源、艙等與旅客人數的最後觀測價格；不同人數或艙等不得混配，且 GUI 應顯示去回程採用的價格來源並區分「航空最佳」與「整體最佳」。
16. GUI 主控台不得把 Mock 與真實流程呈現為同級執行模式；預設必須跑真實流程，只有使用者主動開啟 Debug 開關時才可執行 Mock Pipeline。
17. 設定頁的時段子分頁可用四筆完整時程分別編輯去/回程日期與截止時間；儲存後 `settings.yaml` 更新並立即影響後續篩選，且不得要求重啟服務。
18. GUI 在寬螢幕須維持可讀內容寬度與清楚資訊層級；已配對票價優先於原始航班顯示，Console 與原始航班可收合，任何 API 欄位缺值不得顯示成 `undefined` 或 `null`。
19. 設定頁可將任一完整旅行時程的設定帶入新增表單，但不得立即新增卡片或產生 `_COPY` 類型代碼；使用者必須自行指定唯一代碼並確認新增，且不得覆寫原時程。
20. 設定頁可重新命名時程代碼；空白或重複代碼必須被拒絕，合法改名不得改變原卡排序或其他設定值，且儲存後新代碼立即套用於 GUI 與 Pipeline。
21. Google Flights 目標日期超過可設定的最大提前查詢天數時，Pipeline 必須在本地跳過並輸出明確日誌，且測試須證明該航段未呼叫 crawler 的 `fetch()`；範圍內日期仍正常查詢。
22. Stage 1 以單程搜尋取得航班身分；Stage 2 必須以 Google Flights 真正的來回條件取得完整總價並同時連結去、回程航班實例。GUI 的最終推薦不得再使用兩張單程快照相加。
23. 來回查價須先依嚴格時間與每航空候選上限縮減查詢量；相同來回組合重複價格更新 `last_checked_at`，不同價格保留歷史，且任一航段無法確認時不得寫入正式來回快照。
24. Debug／Mock 模式在任何執行階段都不得呼叫真實 crawler；正式模式的 SSE 進度百分比不得倒退。
25. 正式來回快照只接受同航空公司去回程組合，且必須能在 SQLite 檢視、清除與 Excel 匯出功能中被管理。
26. 時段設定可維護正整數 `query_order`；儲存後 Pipeline 查詢、時段選單、設定卡片與結果排序皆立即依此順序生效，同值維持原始宣告順序，舊設定可自動補值。
27. Google Flights 航班識別 metadata 即使不可見但已附著於 DOM 仍須視為結果已載入；測試須驗證 crawler 使用 `state="attached"`，避免 CI154 類型頁面誤判為 30 秒 Timeout。
28. SQLite 資料庫頁面不得把正式來回的回程出發時間標成「抵達」；須分別顯示去／回程四個時刻、`↔` 航段、旅客／艙等、總額／每人均價及轉換後的台北最後查詢時間。
29. Stage 2 去程清單的航班 metadata 重複或錯標時，crawler 須以候選時刻定位卡片並展開詳情核對航班號；日誌須區分「頁面未提供該航班的可售來回組合」與解析／逾時錯誤。
30. 完整 Pipeline 的正式來回候選不得混入歷史航班實例；單獨 Enrich 才可使用資料庫既有航班。

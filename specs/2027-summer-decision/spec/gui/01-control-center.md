# L2｜主控台

## 目的

建立與監控航班 Pipeline；系統邊界與資料流依 L1 主規格，頁面互動與實作細節以本文件為準。

## 路由、狀態與 API

| 項目 | 契約 |
| --- | --- |
| GUI 區塊 | `#tab-control`，Console 使用 `#console`。 |
| 啟動 | `POST /api/run-pipeline`；回傳 HTTP 202 與 `run_id`。 |
| 日誌 | `GET /api/run-pipeline/{run_id}/events`，SSE `id` 為連續事件序號。 |
| 工作狀態 | `GET /api/run-pipeline/{run_id}`，回傳 `running`、`finished`、`cancelled` 或 `failed`。 |
| 取消 | `POST /api/run-pipeline/{run_id}/cancel`。 |
| 瀏覽器暫存 | `sessionStorage.flightTrackerActivePipeline = { runId, lastEventId }`。 |
| SQLite 寫入 | 工作本身會寫入 `flight_instances`、兩種價格快照與 `crawler_runs`／`crawler_attempts`；頁面不直接寫 DB。 |

### 啟動 request

```json
{
  "run_id": "uuid",
  "mode": "crawl",
  "destinations": ["KIX", "NGO"],
  "windows": ["JULY_SAT", "JULY_SUN"],
  "stage": "all",
  "passenger_profile": {"adults": 2, "children": 2, "infants_in_seat": 0, "infants_on_lap": 0},
  "direct_only": true,
  "export": false,
  "sources": ["google_flights"]
}
```

### SSE event

```json
{"step":"ENRICH","message":"...","percent":78,"level":"info"}
```

`windows` 缺省或空陣列代表全部時段；不得再接受舊版單值 `window`。後端須將目的地與時段去重、依 `query_order` 排序，並回 422 處理未知 IATA、未知時段、空目的地與不合法 `passenger_profile`。

`step` 可為 `INIT`、`SCRAPE`、`NORMALIZE`、`DISCOVER`、`FILTER`、`ENRICH`、`DB`、`EXPORT`、`DONE`、`CANCELLED`、`ERROR`。`percent` 必須為 0–100 且同一工作不可倒退。每個事件另須含 `event_id`、ISO 8601 UTC `occurred_at` 與可選 `attempt_id`；`ERROR` 只可帶 L1 定義的安全 `code` 與 `message`。

## 畫面與操作

- 依序呈現目標航點、旅行時段／階段／旅客組成／直達條件與開始按鈕。主畫面至少可維護大人與兒童；嬰兒佔位／不佔位可放於進階設定。初始旅客組成為 2 位大人與 2 位兒童（共 4 位），並顯示 L1 定義的 `passenger_profile_key`；後續查詢、快照與篩選必須保留此完整組成。
- 正常模式固定執行真實 Google Flights；Mock 僅置於「進階／開發設定」。
- 使用者可選擇 Stage 1、Stage 2 或全部流程，並可多選目的地與時程。時程選擇採 checkbox 清單，提供「全部時段」快捷切換；每個選項的 value 必須是唯一時程代碼（畫面顯示「標籤 · 代碼」），不可將篩選下拉選單的 DOM 納入選取集合。送出時以去重後的 `windows: string[]` 傳送。空陣列代表全部時段，後端須依設定 `query_order` 正規化與去重。
- 執行中顯示階段、百分比、Console、背景工作狀態與「強制中止」。狀態必須提示可切換分頁。
- Console 顯示來源前綴、重試次數與原因、`CANCELLED`／`ERROR` 等事件；同一次查詢必須先輸出 crawler 的 `[SOURCE]`／`[PARSE]` 或 `[SELECT]`／`[RESULT]`，再輸出主控台「取得 N 筆」摘要。這是即時視圖，不是唯一稽核資料來源。
- Console 工具列必須提供「複製日誌」與「清除」。複製以每行可視文字（含前端時間戳）組成純文字，成功顯示「已複製 N 行日誌」後 2 秒還原；無日誌時按鈕 disabled。失敗時顯示可理解提示，不可清除既有日誌。

## Pipeline 邏輯

### Stage 1：發現航班

- 依「出發機場 × 目的地 × 時程日期」以 Google Flights 單程搜尋確認航班號與時刻。
- 完整旅客組成與直達條件必須套用在本階段與 Stage 2；設定後必須驗證 Google UI 回顯的旅客組成，不一致時以 `PASSENGER_PROFILE_MISMATCH` 結束該 attempt，且不得寫入票價快照。航班號格式不合法、空白或 `UNKNOWN` 不得成為航班實例。
- Stage 1 解析後必須依設定 `airlines.<code>.enabled` 過濾；`is_lcc` 僅是航空公司分類，不可作為啟用旗標。未啟用者不可寫入航班實例或單程初估。稽核保存原始卡片數、解析成功數與航空公司排除數。
- 同一航班以飛行日期、航班號與航段去重；重跑只更新最後確認時間。
- 單程頁價格僅可保存為「單程初估」，不可作為正式來回推薦；`price_twd` 一律為完整旅客組成的總價，並保存原始價格文字與 `TOTAL_FOR_PASSENGER_PROFILE` 價格範圍。
- 超過可設定最大提前天數時，在本地直接跳過，不啟動 Playwright。

### Stage 2：補充正式來回票價

- 從已確認航班選出同目的地、同旅行時程、同航空公司的去回程候選；完整流程僅使用本次 Stage 1 的結果，單獨補價才可使用歷史航班。
- 以 Google Flights 來回搜尋選定去程，解析可搭配回程與完整來回總價；兩段皆須對應已確認航班實例才可寫入。去程選取後必須以回程狀態機確認頁面已切換，不可只依賴單一 metadata selector：依序接受 (1) 回程 itinerary metadata、(2)「選擇返回…行程」／「回程航班」等結果狀態文字、(3) 回程結果卡。metadata 存在時優先解析；只有結果卡時，先從卡片子節點的 itinerary metadata 取得真實航班號，仍無法辨識才展開航班詳情，之後再與 Stage 1 回程候選比對。兩路徑都只接受卡片明示的「來回票價／來回總價」。回程三種訊號皆未出現才是「待補查」，必須重載並有限重試；僅在已取得回程結果且無指定組合總價時才為 `NO_SALE_COMBINATION`。
- 同一航空公司的候選數依設定限制；不同航空公司的組合不得寫入正式來回快照。
- 尚未完成的 Stage 2 累積資料只留在記憶體；正常完成才批次寫入。取消時捨棄尚未提交部分。

### 查詢失敗與重試

- 暫時性 timeout、網路或導覽錯誤依爬蟲設定有限重試；Console 顯示第幾次與原因。旅客組成控制項找不到、UI 回顯與 request 不一致屬 `PASSENGER_PROFILE_MISMATCH`，必須保留可診斷原因但不可當成網路錯誤重試。
- 查無結果、日期超限、沒有可售組合屬正常結果，不重試。
- 重試等待期間每 0.1 秒檢查取消訊號；取消後不開始下一次嘗試。

### 爬蟲稽核與診斷紀錄

每次工作建立一筆 `crawler_runs`，每次來源查詢／重試建立 `crawler_attempts`。寫入不可依賴 SSE 是否連線；即使使用者切換頁籤、重新整理或 Console 未顯示，SQLite 仍必須可查。資料表 FK、artifact 與保留策略依資料庫 L2；前端不得自行推導檔案路徑。

| 時點 | 必存欄位 | 診斷規則 |
| --- | --- | --- |
| Stage 1 單程查詢開始 | source、查詢 URL、航段、日期、去／回程類型、旅客數、直達條件、attempt no. | URL 僅含 Google 查詢條件，不含帳號／Cookie。 |
| Stage 2 來回查詢開始 | source、URL、去回程日期、同航空候選去程／回程航班號、旅客數、直達條件、attempt no. | 候選清單必須可追查，例如 `CI112` 與 `CI113`。 |
| 每次結束 | status、結果筆數、解析卡片數、開始／結束時間、錯誤類型與文字 | status 為 `SUCCESS`、`NO_RESULT`、`NO_SALE_COMBINATION`、`RETURN_PENDING_RECHECK`、`PASSENGER_PROFILE_MISMATCH`、`RETRYING`、`FAILED`、`CANCELLED`。 |
| Stage 1 卡片解析不合格 | 依原因統計與每種最多 3 筆安全文字摘要 | 原因至少區分 `MISSING_TIME`、`MISSING_PRICE`、`MISSING_ITINERARY`、`NON_DIRECT`、`PARSE_ERROR`；不得保存完整 HTML、Cookie 或帳號資訊。 |
| 選取去程後回程異常 | 回程 selector、偵測卡片數、目前 URL、頁面標題、候選航班 | 預設保存結構化摘要；設定啟用瀏覽器診斷時另保存 Trace、截圖與安全 Markdown 頁面摘要。 |

UI Console 只顯示容易閱讀的摘要；必須帶 `attempt_id`，使使用者能於資料庫頁查到完整紀錄。不可將完整 HTML、Cookie、帳號或付款資料寫入日誌或 SQLite。

### 瀏覽器診斷模式

「設定 > 爬蟲 > 保存失敗瀏覽器診斷」預設關閉。啟用後，crawler 必須在每個 browser context 開始 Playwright tracing；僅在 attempt 發生例外、去程選取後回程未渲染，或被判定為待補查時，才將下列產物保存並連結至該 attempt。成功 attempt 的 trace 必須停止後丟棄，避免不必要累積。

| 產物 | 保存內容 | 禁止內容 |
| --- | --- | --- |
| `PLAYWRIGHT_TRACE` | Playwright trace zip（操作、DOM snapshot、截圖） | Cookie、request/response body、帳號憑證。 |
| `SCREENSHOT` | 失敗當下的公開結果頁完整截圖 | 使用者帳號、付款或登入頁面；偵測到非公開結果頁時不得保存。 |
| `PAGE_MARKDOWN` | 僅結果主區塊可見文字轉成 Markdown，附 URL、標題與選取航班；長度上限 20,000 字元 | 完整 HTML、表單值、Cookie、帳號或付款資料。 |

產物路徑必須位於 `data/crawler-artifacts/<run_id>/attempt-<attempt_id>/`，資料庫只保存相對路徑、SHA-256、大小與已遮罩 metadata。產物保存失敗不得中斷航班查詢；改記一筆結構化 `BROWSER_ARTIFACT_ERROR` 診斷。這個模式是為了分析 UI 狀態，不可把「缺少既有 selector」直接判定為無票價。

## 背景工作恢復

- 前端須在啟動前保存 `run_id` 與最後 SSE 事件序號。
- 重新整理後查詢工作狀態並重新訂閱遺漏事件；工作已完成、中止或不存在才清除保存值。
- SSE 以 `Last-Event-ID` 或 `after` 恢復，伺服器保留工作事件一小時並每 15 秒傳送 keep-alive。
- 若 POST 回應遺失，前端以已預先保存的 `run_id` 查狀態；同 run ID 的重送必須是 idempotent，不可建立第二個工作。

## 驗收

| ID | 操作 | 預期 |
| --- | --- | --- |
| CC-01 | 以 2 成人、2 兒童啟動完整流程 | request、Google UI 回顯、快照與 audit 的 `passenger_profile_key` 一致。 |
| CC-02 | 傳送未知時段或 adults=0 | API 422，回安全 `code`／`detail`，不建立 run。 |
| CC-03 | SSE 斷線後重新整理 | 背景工作不中止；依 last event 恢復且不重複顯示。 |
| CC-04 | 中止正在 retry 的查詢 | 不開始下一次 retry；已完成 Stage 1 可保留，未提交 Stage 2 資料捨棄。 |
| CC-05 | 回程三種結果訊號皆未出現 | attempt 記為 `RETURN_PENDING_RECHECK`，有限重試，不誤記為無可售組合。 |
| CC-06 | 啟用瀏覽器診斷且 attempt 失敗 | audit 有安全摘要與已登錄 artifact；成功 attempt 不保留 trace。 |
| CC-07 | 完整流程跨階段執行 | `percent` 單調增加，Console 事件可連至正確 `attempt_id`。 |

# L2｜資料庫

## 目的

查核歷史快照與所有已確認航班，並提供安全的匯出與清除操作。

## 路由、元件與 API

| 項目 | 契約 |
| --- | --- |
| GUI 區塊 | `#tab-db`；子頁籤為 `snapshots`、`instances`、`audit`；表格為 `#db-table-body`、`#db-flight-instance-body`、`#crawler-audit-body`。 |
| 快照讀取 | `GET /api/db/snapshots`，回傳單程與正式來回合併資料及筆數。 |
| 實例讀取 | `GET /api/db/flight-instances`。 |
| 爬蟲稽核讀取 | `GET /api/db/crawler-runs?limit=20`；每筆 run 含最近 attempts、失敗診斷摘要與診斷產物 metadata。 |
| 診斷產物讀取 | `GET /api/db/crawler-artifacts/{artifact_id}`；僅提供本機已登錄的相對路徑檔案。 |
| 匯出 | `GET /api/export/excel`。 |
| 清票價 | `DELETE /api/db/snapshots`。 |
| 清全部 | `DELETE /api/db/all`，前端必須二次 `confirm`。 |
| Hash 工具 | 僅測試／查核用途，不可改變正式資料語意。 |

資料庫頁必須使用子頁籤，三個資料 block 不得同時展開造成頁面過長。進入資料庫主頁籤時僅載入目前子頁籤資料；切換子頁籤才呼叫對應 API。搜尋為前端篩選目前的票價快照或航班實例，至少比對日期、航段、航班號、來源與 hash。所有 DB 時間由 UTC 轉 `Asia/Taipei` 才能顯示。

## 畫面與資料

- `snapshots`：同時顯示單程初估與正式來回；正式來回要有去回程日期、航班與四個時間欄位語意。
- `instances`：名稱為「已發現航班實例」，必須包含沒有任何價格的 Stage 1 航班，因此可搜尋到日誌中出現的航班號。提供「僅符合目前時段限制」篩選（預設開啟）與排除原因；可切換查看全部已發現航班。
- `audit`：顯示 crawler run 與可展開的 attempt／diagnostic，不顯示票價快照表與航班實例表。
- 稽核表的結果欄必須依 query kind 呈現正確語意：`ONE_WAY` 顯示「航班 N／結果卡 N」；`ROUNDTRIP` 顯示「組合 N／回程卡 N」。不得將單程已解析航班數誤標為來回組合。
- 三個子頁籤各自提供「複製目前資料」：所有複製內容均採一筆一行、以 `｜` 分隔的純文字，不得使用 Tab，避免貼入對話框時被拆欄或斷行；稽核以 run／attempt／診斷摘要輸出。稽核文字須依 query kind 使用正確欄位名稱，且不得輸出不適用欄位的 `—` 佔位。成功提示複製行數，沒有資料時 disabled；複製失敗不得改變資料或清空畫面。
- SQLite UTC 時間在 GUI 轉成 Asia/Taipei 並標示台北時間。
- 提供關鍵字搜尋、Hash 去重測試、Excel 匯出。
- 「清除票價快照」保留航班實例；「清除全部資料」二次確認後連航班實例一起移除。
- 爬蟲稽核表顯示 run ID、模式、時間、狀態、來源、成功／無結果／失敗數；可展開顯示每次查詢的 URL、候選航班、重試、卡片計數與診斷摘要。
- attempt 有瀏覽器診斷產物時，展開列必須提供「Trace」、「截圖」與「Markdown」連結；不存在的種類不顯示。不得由前端組合磁碟路徑，必須使用 artifact API 的 id。

## 資料模型與去重

### 已確認航班實例

- `flight_instances` 保存飛行日期、去／回程類型、航段、航班號、航空公司、當地出發／抵達時間、直達資訊、來源、是否符合目前嚴格時段、排除原因與最後確認時間。
- 唯一身分為 `flight_date + flight_number + origin_airport + dest_airport`；相同資料再次發現只更新確認時間。

### 單程初估快照

- `flight_price_snapshots` 連結一筆航班實例，保存來源、艙等、完整旅客組成 JSON／`passenger_profile_key`／總人數、原始價格文字、原始幣別／金額、TWD 總價、價格範圍、品質狀態、`run_id`、hash 與最後查詢時間。
- hash 相同的快照不得重複新增；不同來源、`passenger_profile_key` 或艙等必須可獨立保存。

### 正式來回快照

- `roundtrip_price_snapshots` 同時連結去程與回程航班實例，保存時程代碼、總價、來源、完整旅客組成 JSON／`passenger_profile_key`／總人數、艙等、原始價格文字／金額、價格範圍、品質狀態、`quality_reason`、`run_id` 與最後查詢時間。
- GUI 必須把「去程出發／抵達」與「回程出發／抵達」分別呈現，不得以單程欄位誤示。

### 爬蟲稽核資料

- `crawler_runs.run_id` 為 PK；`crawler_attempts.run_id` 為 FK，`crawler_diagnostics.attempt_id` 與 `crawler_artifacts.attempt_id` 為 FK。`DELETE /api/db/all` 必須在同一 transaction 依 artifact、diagnostic、attempt、run 順序刪除；檔案只可刪除已登錄且解析於 artifact root 的路徑。
- `crawler_runs`：`run_id`、mode、stage、目的地／時程／來源／旅客／直達條件的 JSON 快照、開始／完成時間及最終狀態。
- `crawler_attempts`：每次 Stage 1／2 呼叫的 `run_id`、source、query kind、航段與日期、URL、候選去回程 JSON、重試序號、結果／卡片計數、status、錯誤分類及開始／結束時間。
- `crawler_diagnostics`：對應 `attempt_id`，保存 `RETURN_SELECTOR_STATE`、`EXCEPTION` 等 kind 與已遮罩的 JSON 摘要；不得保存 Cookie、帳號、付款資料或完整 HTML。
- `crawler_artifacts`：對應 `attempt_id`，保存 `kind`、相對檔案路徑、SHA-256、檔案大小、已遮罩 metadata 與建立時間。`kind` 限 `PLAYWRIGHT_TRACE`、`SCREENSHOT`、`PAGE_MARKDOWN`；路徑必須解析於 `data/crawler-artifacts/` 內。
- `crawler_attempts` 不參與任何票價、推薦或 Phase 1 計算；它是查核資料，不可因快照 hash 去重而覆蓋。

## API 與匯出

- `GET /api/db/crawler-runs?limit=20&cursor=<opaque>` 回 `{"runs": [], "next_cursor": null}`；每筆 run 的 attempts 限最近 20 筆，較舊資料以 `GET /api/db/crawler-runs/{run_id}/attempts?cursor=` 取得。`limit` 範圍 1–100；非法 cursor 回 422。
- `GET /api/db/crawler-artifacts/{artifact_id}` 僅可讀已登錄、SHA-256 驗證通過且位於 artifact root 的檔案；不存在、已清理或校驗失敗均回 404，不得洩漏本機絕對路徑。
- 快照列的 `quality_status` 限 L1 的 `VALID`、`STALE`、`INVALID`，並回傳 `quality_reason`。所有推薦與 Phase 1 一律只讀 `VALID` 正式來回快照。
- `GET /api/db/snapshots` 同時回傳單程與正式來回快照；推薦計算僅使用 `quality_status=VALID` 的正式來回快照。`GET /api/db/flight-instances?strict_only=true` 預設回傳符合時段者；可傳 `strict_only=false` 查看全部發現航班。
- 航班的來回狀態必須分別呈現本次 run 與歷史狀態：`MATCHED_CURRENT_RUN`、`RETURN_PENDING_RECHECK`、`NO_SALE_CURRENT_RUN`、`HISTORICAL_MATCH_ONLY`、`NOT_QUERIED`；不得以單一 `has_roundtrip_price` 掩蓋本次失敗。
- `DELETE /api/db/snapshots` 僅清快照；`DELETE /api/db/all` 依 artifact、診斷、attempt、run、正式來回、單程、航班實例順序清除，並只刪除 `data/crawler-artifacts/` 內已登錄的檔案。
- Excel 匯出至少分為單程初估與正式來回兩張工作表。

## 驗收

| ID | 操作 | 預期 |
| --- | --- | --- |
| DB-01 | 切換 snapshots／instances／audit 子頁籤 | 僅載入目前子頁籤 API，三塊資料不會同時展開。 |
| DB-02 | 檢視同總人數、不同旅客組成快照 | 依不同 `passenger_profile_key` 分列，不被錯誤去重或混用。 |
| DB-03 | 讀取 audit 分頁並展開 run | 可分頁讀取 attempts；ONE_WAY 與 ROUNDTRIP 使用正確計數文字。 |
| DB-04 | 取得已清理或路徑不合法的 artifact | API 404，前端顯示安全提示，不顯示絕對路徑。 |
| DB-05 | 清除票價快照 | 僅清除兩種價格快照；航班與 audit 保留，畫面與狀態列同步。 |
| DB-06 | 清除全部資料 | 二次確認後在 transaction 清除登錄 artifact、audit、快照與實例；未登錄檔案不可被刪除。 |

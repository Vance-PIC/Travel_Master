# L2｜Phase 1 航點評比

## 目的

把各航點最低有效正式來回票價，加上設定的住宿與地面交通預估，協助橫向比較。

## 路由、資料來源與 API

| 項目 | 契約 |
| --- | --- |
| GUI 區塊 | `#tab-matrix`。 |
| API | `GET /api/phase1?passenger_profile_key=&cabin_class=`，切換頁籤時重新取得。 |
| DB 對應 | 讀取 `roundtrip_price_snapshots` 與其關聯的 `flight_instances`；不使用單程初估。 |
| YAML 對應 | `destinations` 決定列順序；`phase1_costs.<IATA>.accommodation`、`ground_transport` 提供非機票成本。 |
| 寫入 | 無。 |

回應列格式為 `{ iata, name_zh, matched_schedules, passenger_profile_key, airfare, accommodation, ground_transport, total }`；`airfare` 或 `total` 無資料時前端顯示 `—`，不得以 0 偽裝有票價。未知 profile／艙等回 422；載入失敗時保留最後成功圖表並顯示重試操作。

## 畫面與資料

- 顯示橫向堆疊圖：機票、住宿、地面交通。
- 每個航點顯示符合配對組數與最低預估總額；無有效機票時明確顯示尚無可配對票價。
- 幣別固定 TWD；費用組成與 `phase1_costs` 的資料來源需可辨識。

## 計算邏輯

- 每個目的地只取符合 L2 航班決策規則且 `quality_status=VALID` 的正式來回票價最低值。
- 住宿與地面交通為每位佔位旅客固定預估；總額為正式來回總價、住宿與地面交通之和，三者必須使用同一個 `passenger_profile_key` 的人數基礎。
- 無正式來回票價時，保留住宿與交通資訊供比較，但不可虛構總額或推薦航點。

## 驗收

| ID | 操作 | 預期 |
| --- | --- | --- |
| P1-01 | 切換旅客組成 | 圖表、卡片與機票候選使用相同 `passenger_profile_key`。 |
| P1-02 | 僅有 STALE／INVALID 快照 | 不計為票價或推薦，仍可顯示住宿與交通。 |
| P1-03 | API 載入失敗 | 保留最後成功圖表並提供重試；不以 0 覆蓋資料。 |

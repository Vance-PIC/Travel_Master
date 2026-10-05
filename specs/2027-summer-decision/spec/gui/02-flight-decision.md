# L2｜航班決策

## 目的

先呈現可決策的正式來回票價，再提供 Stage 1 已確認航班供查核。

## 路由、資料來源與 API

| 項目 | 契約 |
| --- | --- |
| GUI 區塊 | `#tab-flights`。 |
| 主結果 API | `GET /api/flight-schedule?dest=&window=&strict=&passenger_profile_key=&cabin_class=`。 |
| 原始航班 API | `GET /api/flight-instances?dest=&window=&strict_only=&has_price=`。 |
| 設定依賴 | `GET /api/settings` 的 `windows`、`airlines`、`destinations`。 |
| 讀取 DB | 主結果讀 `roundtrip_price_snapshots` join 兩筆 `flight_instances`；原始區讀 `flight_instances`。 |
| 寫入 DB | 無；人工補單程價時才使用 `POST /api/flight-instances/{id}/enrichment`，該操作不在主結果表直接執行。 |

`/api/flight-schedule` 回應 `{ count, rows }`。每列至少包含目的地、時程、去回程航空公司／航班號／日期時間、`passenger_profile`、`passenger_profile_key`、艙等、正式來回總價、來源、`quality_status`、`is_airline_best`、`is_recommended` 與 `note`。僅回 `quality_status=VALID` 的正式來回快照；未知時段／profile／艙等回 422，API 或網路失敗時保留上一份成功資料並顯示可重試錯誤。

## 畫面與資料

- 篩選條件：目的地、時程、嚴格時間規則、完整旅客組成與艙等；不得以總人數替代旅客組成。
- 主表使用正式 `roundtrip_price_snapshots`，只顯示同航空公司、符合 L1 時間規則的可配對結果。
- 顯示航空最佳與整體推薦的不同標記；沒有資料時顯示 `—`，不得顯示 `undefined`／`null`。
- 原始航班以可收合的「已確認航班實例」呈現，並標示是否已有單程初估或正式來回價格。

## 嚴格時間與推薦邏輯

- 每個時程以「去程截止日期時間＋回程截止日期時間」表示；航班出發時間必須嚴格早於截止時間。
- 標準規則為去程週日早於 15:00、週六回程早於 20:00、週日回程早於 14:00；實際日期時間以設定時程為準。
- 先排除設定為不納入查詢的航空公司與不符合時間規則的配對。
- 每個「目的地 × 月份群組 × 航空公司 × 艙等 × `passenger_profile_key`」選一筆航空最佳；再跨航空公司選一筆整體推薦。
- 排序以正式來回總價由低到高；同價時優先較長行程，再依回程出發時間較晚者優先。
- 歷史快照先依「航班實例／來源／艙等／旅客數」取最新觀測，再比較不同來源的有效價；不得使用歷史最低價覆蓋現價。

## 驗收

| ID | 操作 | 預期 |
| --- | --- | --- |
| FD-01 | 同時存在單程初估與正式來回快照 | 主表只顯示 `VALID` 正式來回總價。 |
| FD-02 | 相同 4 人但組成不同 | 依 `passenger_profile_key` 分開篩選、排名與推薦。 |
| FD-03 | 切換 strict 篩選 | 不合格列僅在關閉 strict 時供查核，不能有最佳旗標。 |
| FD-04 | 查詢回 422／500 | 保留上一份成功表格、顯示錯誤與重試，不顯示 `null`／`undefined`。 |

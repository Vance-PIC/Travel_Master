# 住宿持久化與報告契約

## 持久化（未執行前不建監控資料）

以 repo-relative `persistence_root/<monitor_id>/` 區分案例。首次真實執行後才產生資料；路徑必須留在 persistence_root 内，monitor_id 不接受路徑跳脫。報告模式不建立或改寫監控檔案。

- `latest.json`：最後成功且完整驗證的該案例 snapshot。包含 schema_version、monitor_id、stage、comparison_key、config 指紋、run_id、checked_at、coverage、observations。每筆 room/rate 有自己的 observed_at、source、identity、stay／party、條件證據、價格語意、Stage 判定與 fresh/retained 標記。跨來源資料不可拼接成不存在的 rate。
- `history.csv`：只追加實際新觀察。欄位至少 schema_version、run_id、monitor_id、stage、comparison_key、observed_at、source、hotel_key、room_key、rate_key、status、amount、currency、price_scope、tax_fee_inclusion、filter_status、room_match、comparison_status、evidence_ref。證據完整物件保存在成功 snapshot 的不可變版本 `snapshots/<run_id>.json`，history 的 evidence_ref 指向該版本，不能指向會覆寫的 latest。unknown 數值為空，不是零。
- `last-run.json`：最新一次真實執行嘗試的 run_id、stage、開始／結束時間、success/error/partial/skipped、requested/completed/deferred/failed sources、安全錯誤與 snapshot_run_id。沒有執行就不建立。設定檢查不是一次查價。

全部必要查詢與解析成功後，才發布不可變 snapshot、history 與 latest 的同一 run_id。未來 executor 必須實作可恢復的寫入交易／暫存機制，不能因寫檔中斷留下 history/latest 不一致。任何必要來源/API/解析失敗或部分完成時，保留原 latest/history；只寫 last-run 診斷，partial 不發布為有效新 snapshot。明確成功的空結果可存空觀察，不能偽造零價。

保留資料不更新 observed_at，不重複追加 history；not_returned 只適用成功查詢的同一 coverage，不代表確定售罄。歷史價格僅比較相同 stage、comparison_key、currency、scope、稅費與必要 rate 條件；Stage 1 與 Stage 2 不混合計算低點。設定變更不得回填舊資料為新條件。保留未知 CSV 欄位，遷移需明確版本。

## 報告共同要求

只讀設定、latest/history/last-run；產生報告不觸發 API。無 snapshot 顯示「尚未執行住宿監控」，只列設定與待補欄位，不生成候選、價格或 history。設定與 snapshot 的 comparison_key／指紋不符時，標示舊設定資料，不能用新 baseline 計算差額。

開頭列案例 Stage、住宿日期、人數／房數與幣別。每筆報價顯示原 observed_at（時區／offset）與來源連結／文件識別，不以報告時間代替。未知價格／條件顯示待確認；幣別未知只顯示數字與「幣別未知」，不用貨幣符號。每晚、每房、每人、全程總價各自標示，不混排或比較。

## Stage 1：哪些候選真正符合需求？

主表僅 qualified 的具體 room/rate；同館不同合格 rate 可分列。不存在合格結果就說「無已證實符合全部硬條件的候選」，不能拿 pending 補表。

| 飯店 | 房型／rate | 面積 | 入住組合／房數 | 床型 | 禁菸 | 區域／交通證據 | 價格／幣別／scope／稅費 | 來源 | 條件狀態與證據 | 資料時間 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

另列 pending_confirmation 表，包含未知欄位與證據缺口；excluded 可列原因摘要，價格不列作候選低價。Preferences 顯示符合／不符／未知，不把偏好不符改成 Hard Filter 排除。飯店起價如需展示，置於獨立 discovery 訊號區並註明非合格候選報價。

## Stage 2：是否有真正可替代的更低價格？

先列 booked baseline 的房型與政策、金額、currency/source/scope/稅費及證據缺口。正式比較主表僅房型合格且 comparison_status=comparable 的報價。

| 來源 | 飯店 | 房型／rate | room_match | 逐欄證據 | 目前價格 | 已訂 baseline | 差額 | 取消／付款／benefits | 資料時間 | 通知門檻／是否達標 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

差額為 current-baseline，明確顯示正負。只有價格、政策、資格與新鮮度均可比才能填數字差額；通知使用 search-policy 的严格小於規則。exact_match 本身不保證價格或政策可比。

獨立待確認表列 uncertain 或其他 pending_confirmation 報價及缺口，差額／門檻判定為「待確認」，不得標示降價、節省或通知達標。mismatch/not_comparable 排除，列不符原因，不放入降價排行榜。

## 執行與資料狀態

結尾列 last-run 狀態、來源 coverage 與缺失／失敗原因。失敗後使用舊 snapshot 時，顯示「最後有效資料，非本次更新」與原時間；逾設定新鮮度標 stale，未設新鮮度標待確認。保留報價不觸發新通知。未執行、空觀察、來源失敗、待確認與真正無合格候選必須區別；不得宣稱全市場涵蓋、可訂保證或未有證據的取消權利。

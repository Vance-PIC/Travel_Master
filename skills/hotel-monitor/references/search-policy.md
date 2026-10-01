# 住宿搜尋與比較政策

## 設定契約（schema_version 1）

trip config 包含 `trip_id`、`execution`、`persistence_root` 與 `monitors`。每個 monitor 有唯一 `monitor_id`、`stage`、`stay`、`party`、`hard_filters`、`preferences`、`sources` 與 `evidence`。日期為住宿地當地日期，check_out 必須晚於 check_in。party 包含 adults、children、child_ages、rooms；缺少年齡或房數記 null，不能填預設值。child_ages 非 null 時須與 children 數量一致；年齡採入住日年齡。

Stage 1 以需求為中心，無需 hotel 或 room_baseline。`hard_filters.location` 支援文字區域、交通站數與待補距離；`min_room_size_m2`、`beds.count/type`、`smoking`、`occupancy`、`price_ceiling` 皆由案例指定。Preferences 獨立保存。未知參數若為來源查詢必填，先回報缺口，不用猜測參數送出查詢。

Stage 2 額外有 `hotel_identity`、`room_baseline`、`booking_baseline`、`alert`。identity 包含名稱、地址、source_ids 與證據；尚無地址／ID 時，不以同名視為同館。room_baseline 包含 name、size_m2、beds、smoking。booking_baseline 包含 amount、currency、source、price_scope、tax_fee_inclusion、cancellation、payment、benefits 及 evidence。未知政策與 benefits 是 null，而非「不可退」、「立即付款」或「無早餐」。`alert.operator=lt` 代表严格小於門檻，等於不觸發；未知門檻幣別不得直接套用報價幣別。

`sources=[]` 表示尚無已設定來源，不暗示搜尋完成。evidence 區分使用者陳述、訂單文件、來源頁面或既有實驗；設定不是查價結果。價格 scope 未確認時為 unknown，不能從入住天數或已訂金額推定為全程總價。變更日期、人數、房型、條件或 baseline 後產生新的 comparison_key，不串接旧基準。

## Stage 1：Hard Filters 與證據

對具體 room/rate 逐项評估日期可訂性、完整 occupancy（含實際兒童年齡／同住規則）、房數、面積、床數／床型、禁菸、區域／交通及已設定的其他硬條件。不能把飯店公共設施或其他房型的資料當作此房型證據。Twin 名稱不能單獨證明實際兩床與尺寸；床數也不能證明可住全體人員。unknown 不淘汰為 fail，但只能進待確認區，不能列為合格候選。

位置的「附近」若尚無明確距離，保持定性要求；不得自創公里／步行分鐘門檻。交通一站需路線、起終站、停站數及抵達飯店的交通證據；資料不足保持 unknown。不能只依地名判 pass。

每份證據至少有 field、literal_value、source（頁面／文件識別）、safe_url 或 repo_path、observed_at；若來源 publication_time 已知另外保存，勿用報告時間替代觀察時間。缺證據不得填入假時間。來源沒有某欄位不代表條件符合。

价格保存實際 room_id/name、rate_id/name、availability、source、observed_at、amount、currency、price_scope、tax_fee_inclusion 與查詢入住參數。不知道 room/rate 的飯店起價只能作獨立 discovery 訊號，不能當候選報價。只有可比總價可排序為「最便宜」，其餘按條件或偏好排序並標價格待確認。

## Stage 2：房型匹配

| classification | 判定 | 正式比較資格 |
| --- | --- | --- |
| exact_match | 已證實同館、同日期／party／房數，來源 room ID 或其他直接證據對應已訂房型，面積／床型／禁菸全部一致且無矛盾 | 有，仍需價格／訂單條件通過 |
| equivalent | 名稱或來源 ID 不同，但同館與全部必要物理條件有逐欄證據支持等價，不以相似名稱推定 | 有，仍需價格／訂單條件通過 |
| uncertain | identity 或任何必要條件缺失、歧義、證據互相矛盾未解決 | 無；待確認 |
| mismatch | 有明確證據不符合任一鎖定條件，例如別館、不同入住組合、較小房、不同床型或可吸菸 | 無；排除 |

必要條件缺證據即 uncertain；已確定的不符優先 mismatch。不得只因面積較大或房名更高級就判 equivalent。保存各欄位 baseline、quote、判定、證據與 classification_reason。

## 價格／訂單條件可比性與通知

`room_match` 與 `comparison_status` 是兩個獨立判定。正式比較要求：

1. room_match 是 exact_match 或證據充分的 equivalent，且報價新鮮、可訂；新鮮度使用設定的 max_quote_age_hours，未設定不得自行認定仍有效。
2. 相同已確認 currency、相同全程／全房／全入住組合的 total_stay_all_rooms_party scope；完整日期、人數、房數與兒童政策一致。不得乘每晚起價、乘房數或人數來推算總價。若來源直接提供有證據的全程總價，以該報價獨立保存。
3. baseline 與 quote 的稅費包含方式明確一致，所有必付費用明確；未知稅費不視為零。會員、app、優惠碼或居住地限制需實際資格證據，否則待確認。
4. 有證據的 baseline 取消／付款／benefits 必須逐項相同；如有差異，獨立標示，除非使用者明確接受且留下證據，不能正式視為替代方案。未知 baseline 條件先補證據，不能當萬用匹配。取消 deadline 要有時區與罰金，付款含付款時點與幣別，benefits 含餐食／其他包含項目。

全通過才 `comparison_status=comparable`；缺證據為 pending_confirmation；已知不符為 not_comparable。僅 comparable 可計算 `difference=current-baseline`；負值為更便宜。通知还要求同幣別、同 scope 的有效門檻、fresh quote、difference < 0 以及 current < threshold。其他情況 `difference=null`、`alert_reached=null` 並列原因；合格但未達門檻為 false。保留報價不得觸發新通知，也不能將某來源條件驗證套到別的 rate。

跨站比較不承諾涵蓋所有來源；記錄 requested/completed/deferred/failed sources。空結果是該来源本次未返回，不是全市場無房或價格零。失敗、部分完成與 deferred 均不得宣稱完整查詢。

## 本期邊界

只建立契約，不提供 API adapter、不查價、不重跑住宿實驗、不排程、不寫虛構 snapshot/history。之後新增 executor 時先檢查現有 API 成果並引用，不自行重新實驗。

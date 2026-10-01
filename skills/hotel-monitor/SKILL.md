---
name: hotel-monitor
description: Use when searching for accommodation candidates that meet a party's requirements or comparing an already booked hotel room across sources, including hotel price monitoring and reports.
---

# Hotel Monitor

住宿監控原生分為 `candidate_search` 與 `booked_room_compare`。由使用者指定的 trip-specific config 載入案例，以 `monitor_id` 選擇 Stage；不得因另一 Stage 有價格而自動轉換。旅程日期、飯店、人數、房型、金額與來源都放在設定，不寫入通用 Skill。

查詢與判讀前讀取 [search-policy.md](references/search-policy.md)；保存或產生報告時讀取 [report-format.md](references/report-format.md)。設定契約與持久化契約分別定義於這兩份 reference。

## Stage 1：candidate_search

尚未決定飯店／房型時，以日期、人數、房數、區域／交通、面積、床型、禁菸與其他 Hard Filters 尋找實際符合需求的 room/rate。飯店名稱與特定房型不是必要搜尋條件。Preferences 只排序或標示，不取代 Hard Filters。

每個 Hard Filter 分別記錄 `pass/fail/unknown` 與證據。全部 pass 才是 `qualified`；任一 fail 為 `excluded`；其餘 `pending_confirmation`。未知不是符合。價格必須綁定該合格 room/rate，不得以飯店最低價、雙人價或其他房型低價代替。

## Stage 2：booked_room_compare

鎖定飯店 identity、日期、完整入住組合、房數與已訂 room baseline（面積、床型、禁菸），以及有證據的取消、付款、benefits。不要只比房型名称字串。分類為 `exact_match/equivalent/uncertain/mismatch`；只有 exact_match 或證據充分的 equivalent 才有資格進入正式比價，且仍須通過價格與訂單條件的可比性檢查。

uncertain 只能待確認，mismatch 排除；兩者的差額與通知判定均為 null。不同房型便宜不等於已訂方案降價。即使房型一致，幣別、總價範圍、稅費或必要訂單條件未知也不成立正式替代結論。

## 執行邊界

目前提供 Skill、設定契約及 [SearchAPI 手動能力驗證 adapter](references/searchapi-adapter.md)。正式 executor 已提供 `scripts/hotel_executor.py`，按逐欄證據評估 Stage 1／Stage 2 並保存紀錄；資料不足不得宣稱已完成正式比價。`execution.query_enabled=false` 與 `schedule_enabled=false` 禁止自動監控查詢；使用者明確授權的單次 executor 可用 `--allow-query`，不修改設定或 schedule。能力驗證仍使用獨立入口，每次最多五個請求，只產生驗證 artifact。不得重跑已驗證住宿 API 實驗或建立 schedule。

來源實驗若已存在，引用其檔案與證據，不重新驗證，也不將實驗資料當正式 snapshot。未知維持 unknown/null，不猜兒童年齡、加床、免費同住、幣別、訂房來源或取消政策。報告只讀既有資料，不觸發查詢；無 snapshot 就說尚未執行。

成功觀察、歷史與最新嘗試分開保存；失敗保留最後有效 snapshot/history，僅更新安全的 last-run 診斷。不要保存密碼、API key、訂單編號、個資、簽章或帶敏感參數的 URL。遇到 CAPTCHA／封鎖停止，不繞過。此 Skill 不授權訂房、付款、取消原訂單或遠端發布。

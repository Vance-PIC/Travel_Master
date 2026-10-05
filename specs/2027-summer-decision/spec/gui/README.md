# GUI L2 規格索引

本資料夾依 Web GUI 頁籤拆分 L2 規格，供 PG 直接實作。L1 主規格只定義系統邊界、架構與資料流；L2 是各頁的實作契約。

| 頁籤 | L2 文件 |
| --- | --- |
| 主控台 | [01-control-center.md](01-control-center.md) |
| 航班決策 | [02-flight-decision.md](02-flight-decision.md) |
| Phase 1 航點評比 | [03-phase1-comparison.md](03-phase1-comparison.md) |
| 資料庫 | [04-database-inspector.md](04-database-inspector.md) |
| AI 顧問 | [05-ai-advisor.md](05-ai-advisor.md) |
| 設定 | [06-settings.md](06-settings.md) |

每一份 L2 必須包含：頁面目的與路由、元件／狀態、資料來源與 DB 對應、API request／response、讀寫副作用、商業／驗證邏輯、錯誤處理、驗收案例。跨頁資料流由 L1 說明，但具體欄位與邏輯必須落在使用該資料的 L2。

衝突處理順序：使用者需求 > L1 系統邊界 > 對應 L2 實作契約 > 程式註解。

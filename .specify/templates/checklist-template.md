# UAT Verification Checklist: Track [TrackID] ([任務名稱])

## 1. 基礎環境驗證 (Infrastructure)
- [ ] **版本號一致性**：確認 `Constants.gs` 與各終端輸出的版號符合預期。
- [ ] **配置正確性**：確認 `appsettings.json` 或相關環境變數已正確載入。

## 2. 核心功能驗證 (Functional)
- [ ] **[關鍵場景 A]**：
- [ ] **[關鍵場景 B]**：
- [ ] **邊界條件測試**：測試異常輸入或空值狀態。

## 3. 性能與穩健性驗證 (Quality)
- [ ] **回應時間**：觀察同步或 UI 渲染是否符合效能指標。
- [ ] **抗震測試**：驗證 Retry 機制或錯誤捕捉是否如預期運作。
- [ ] **回歸測試**：確保新功能未破壞現有的舊有邏輯。

---
*產出日期：[DATE]*
*驗收人員：Owner*
*測試結果：[PASS / FAIL / PENDING]*

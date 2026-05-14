# Track [TrackID]: [任務名稱] (實作計畫)

> **Status: [STRATEGIZING]**
> **治理提醒**: 本計畫嚴格對齊 `workflow.md` 標準。執行任何 Checkpoint 後，必須遵循「後置打卡」原則：實作 ➔ 驗證 ➔ 物理勾選 [x]。

## Phase 1: Research & Context (研究階段)
- [ ] **物理偵查與證據盤點**：執行 `grep_search` 或 `glob` 定位問題。
- [ ] **產出研究報告**：完成 `research_report.md` 並貼出原始數據證據。
- [ ] **初始化開發日誌**：於 `journal.md` 記錄初始環境狀態。
- [ ] **通過 Gate-P1 審計**：執行 `scripts/10_gate-p1-research.ps1`。

## Phase 2: Strategy & Design (設計階段)
- [ ] **產出技術規格書**：完成 `spec.md` (包含「實體檔案影響清單」與 3 方案評比)。
- [ ] **建立 UAT 測試案例骨架**：產出 `UAT_CHECKLIST.md` 定義驗收標準。
- [ ] **細化實作步驟**：更新本文件 (`plan.md`) 之 Phase 3 具體 Tasks。
- [ ] **通過 Gate-P2 審計**：執行 `scripts/20_gate-p2-design.ps1` 獲取實作授權。

## Phase 3: Execution (實作階段)
- [ ] **環境預檢 (Preflight)**：呼叫 `scripts/30_gate-preflight-check.ps1` 並確保 Clean Branch。
- [ ] **實作核心邏輯**：依照 `spec.md` 決策進行代碼撰寫。
- [ ] **配合實作優化 UAT 測試案例**：根據實作細節補強 `UAT_CHECKLIST.md`。
- [ ] **更新實作證據**：於 `journal.md` 記錄關鍵代碼變更或遭遇之問題。
- [ ] **通過單元測試**：執行 `dotnet test` 或相關驗證工具。

## Phase 4: Verification & Handover (驗證階段)
- [ ] **影子部署 (Shadow Deploy)**：執行 `scripts/32_release_track.ps1` 提供 UAT 環境。
- [ ] **執行全量 UAT 驗收**：手動或自動執行 `UAT_CHECKLIST.md` 並記錄結果。
- [ ] **產出交付證據**：於 `journal.md` 貼出測試成功的截圖或日誌。
- [ ] **通過 Gate-P4 審計**：執行 `scripts/40_gate-p4-handover.ps1`。

## Phase 5: Closure & Archive (結案程序)
- [ ] **合併主線**：將開發分支變更合併回 `master/main`。
- [ ] **物理版號晉升**：確認 V 號晉升邏輯（Major/Minor/Patch）。
- [ ] **Dev 環境發布**：執行 `scripts/50_release_dev.ps1`（視需求傳入 `-NewVersion`）。
- [ ] **更新 Release Note**：將變更記錄至 `knowledge/RELEASE_HISTORY.md`。
- [ ] **資源回收與歸檔**：執行 `scripts/53_teardown_track.ps1` 並物理搬移目錄至 archive。

## Rollback Plan
- **代碼回退**：`git checkout HEAD`。
- **環境還原**：(在此列出還原步驟)

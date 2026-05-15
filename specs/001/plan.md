# Track 001: 拆分熊本旅遊手冊為多個章節檔案 (實作計畫)

> **Status: [VERIFYING]**
> **治理提醒**: 本計畫嚴格對齊 `workflow.md` 標準。執行任何 Checkpoint 後，必須遵循「後置打卡」原則：實作 ➔ 驗證 ➔ 物理勾選 [x]。

## Phase 1: Research & Context (研究階段)
- [x] **物理偵查與證據盤點**：執行 `grep_search` 或 `glob` 定位問題。
- [x] **產出研究報告**：完成 `research_report.md` 並貼出原始數據證據。
- [x] **初始化開發日誌**：於 `journal.md` 記錄初始環境狀態。
- [x] **通過 Gate-P1 審計**：執行 `scripts/10_gate-p1-research.ps1`。

## Phase 2: Strategy & Design (設計階段)
- [x] **產出技術規格書**：完成 `spec.md` (包含「實體檔案影響清單」與 3 方案評比)。
- [x] **建立 UAT 測試案例骨架**：產出 `UAT_CHECKLIST.md` 定義驗收標準。
- [x] **細化實作步驟**：更新本文件 (`plan.md`) 之 Phase 3 具體 Tasks。
- [x] **通過 Gate-P2 審計**：執行 `scripts/20_gate-p2-design.ps1` 獲取實作授權。

## Phase 3: Execution (實作階段)
- [x] **環境預檢 (Preflight)**：呼叫 `scripts/30_gate-preflight-check.ps1` 並確保 Clean Branch。
- [x] **執行檔案拆分**：
  - [x] 產生 `01_Chapter1_核心戰報與財務預算.md`
  - [x] 產生 `02_Day1_抵達熊本.md`
  - [x] 產生 `03_Day2_熊本城巡禮.md`
  - [x] 產生 `04_Day3_Greenland全日遊.md`
  - [x] 產生 `05_Day4_挺進阿蘇.md`
  - [x] 產生 `06_Day5_農場深度玩與和牛烤肉.md`
  - [x] 產生 `07_Day6_阿蘇神社巡禮.md`
  - [x] 產生 `08_Day7_機場最後衝刺.md`
- [x] **配合實作優化 UAT 測試案例**：根據實作細節補強 `UAT_CHECKLIST.md`。
- [x] **更新實作證據**：於 `journal.md` 記錄關鍵代碼變更或遭遇之問題。

## Phase 4: Verification & Handover (驗證階段)
- [x] **執行全量 UAT 驗收**：手動或自動執行 `UAT_CHECKLIST.md` 並記錄結果。
- [x] **產出交付證據**：於 `journal.md` 貼出測試成功的截圖或日誌。
- [ ] **通過 Gate-P4 審計**：執行 `scripts/40_gate-p4-handover.ps1`。

## Phase 5: Closure & Archive (結案程序)
- [ ] **合併主線**：將開發分支變更合併回 `master/main`。
- [ ] **物理版號晉升**：確認 V 號晉升邏輯（Major/Minor/Patch）。
- [ ] **資源回收與歸檔**：執行 `scripts/53_teardown_track.ps1` 並物理搬移目錄至 archive。

## Rollback Plan
- **代碼回退**：`git checkout HEAD`。
- **環境還原**：刪除產生的 md 檔案。

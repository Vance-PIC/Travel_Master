# Workflow: PIC-WorkFlow

本專案採用 PIC-WorkFlow (SpecKit + Conductor) 開發模式。

## 1. 核心開發紀律 (Discipline)
- **Rule 1: 全文件零省略 (Zero Omission)**: 任何 Markdown 異動必須全量展開。嚴禁使用 `(略)` 或 `...`。
- **Rule 2: 物理手煞車 (Preflight Lock)**: 在執行代碼修改前，必須通過 `scripts/30_gate-preflight-check.ps1` 檢核。
- **Rule 3: 看板聯動 (Dashboard Sync)**: 任何進度更新必須同步至 `conductor/tracks.md`。
- **Rule 4: 分支隔離 (Isolation)**: 實作階段必須在 `track/[ID]-[name]` 分支進行。

## 2. 開發階段矩陣 (P1~P5 Matrix)

| 階段 | 狀態標籤 | 目標 | 負責人 | 物理路徑 | 下一階段 | 檢核點 | 說明 | 產出物 (Required) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P1: 研究** | [RESEARCHING] | 鎖定根因 | AI | specs/[ID] | P2 | 報告完成 | 技術調研與問題定義 | research_report.md, journal.md |
| **P2: 策略** | [STRATEGIZING] | 設計方案 | AI | specs/[ID] | P3 | 方案核准 | 架構設計與實作計畫 | spec.md, plan.md |
| **P3: 實作** | [IN EXECUTION] | 完成施工 | AI | src/ | P4 | 測試通過 | 代碼開發與單元測試 | (Implementation) |
| **P4: 驗證** | [VERIFYING] | 系統驗收 | User | specs/[ID] | P5 | 驗收合格 | UAT 測試與手動驗核 | UAT_CHECKLIST.md |
| **P5: 結案** | [DONE] | 歸檔發布 | AI | archive/ | - | 任務關閉 | 物理歸檔與版號晉升 | journal.md |

## 3. 核心指令
- 建立新功能: `scripts/00_create-new-feature.ps1`
- 同步看板: `scripts/90_sync_dashboard.ps1`
- 提交預檢: `scripts/30_gate-preflight-check.ps1`

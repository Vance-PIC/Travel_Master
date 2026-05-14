# Project Rules: 熊本旅遊實作

## 1. 治理框架
本專案嚴格遵循 **PIC-WorkFlow (SpecKit + Conductor)** 治理規範。所有開發活動必須對齊 P1~P5 階段。

## 2. 核心指令
- **啟動新任務**: `pwsh -NoProfile -File scripts/00_create-new-feature.ps1 "任務描述"`
- **提交代碼前預檢**: `pwsh -NoProfile -File scripts/30_gate-preflight-check.ps1`
- **手動同步看板**: `pwsh -NoProfile -File scripts/90_sync_dashboard.ps1 -TrackID "ID" -Status "[STATUS]"`

## 3. 工程紀律
- **零省略原則**: Markdown 文件嚴禁使用 `(略)`。
- **物理手煞車**: 必須通過 preflight-check 才能進行寫入操作。
- **看板同步**: 每個 Checkpoint 完成後必須立即執行 `90_sync_dashboard.ps1`。
- **樣式規範**: 遵循 Rule 11，禁止在 HTML 中硬編碼超過 3 個 Tailwind/CSS 類別，應提取至全域樣式表。

## 4. 目錄結構
- `src/`: 源碼目錄
- `scripts/`: 自動化腳本
- `specs/`: 開發中任務文件 (P1~P4)
- `conductor/`: 專案看板與工作流定義
- `.specify/templates/`: 治理範本
- `knowledge/archive/`: 已結案任務歸檔 (P5)

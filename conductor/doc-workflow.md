# Workflow: Doc-Gov (Document Governance)

本專案採用專為文件撰寫與知識庫管理設計的 **Doc-Gov** 工作流。

## 1. 核心開發紀律 (Discipline)
- **零省略原則**: 任何 Markdown 異動必須全量展開。嚴禁使用 `(略)` 或 `...`。
- **範本驅動**: 所有的內容撰寫必須對齊 D1 階段確定的範本格式與表格結構。
- **物理拆分**: 為了提升效能與並行撰寫，大型手冊應拆分為獨立的章節檔案。
- **自動化審計**: 提交前必須通過 `scripts/audit-doc.ps1` 檢核。

## 2. 五階段矩陣 (D1~D5 Matrix)

| 階段 | 名稱 | 目標 | 物理產出 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| **D1** | **Context** | 背景與範本確認 | `context.md` | 釐清專案目的、格式與特殊表格範本。 |
| **D2** | **Structure** | 章節拆分與大綱 | `outline.md` | 依照範本結構將文件拆分為多個 .md 檔案。 |
| **D3** | **Authoring** | 內容撰寫 | `src/*.md` | 依照大綱與範本進行撰寫，確保內容全量展開。 |
| **D4** | **Authoring** | 內容撰寫與補完 | `src/*.md` | 採用「八步協作流程 (Step 1~7)」進行撰寫，並通過 `audit-chapter.ps1`。 |
| **D5** | **Release** | 合併發布 | `OUTPUT.md` | 執行「Step 8: 發布」，合併章節並自動晉升版號 (+0.01)。 |

## 3. 核心指令
- **執行文件審計**: `pwsh -NoProfile -File scripts/audit-doc.ps1`
- **執行文件合併**: `pwsh -NoProfile -File scripts/merge-doc.ps1`

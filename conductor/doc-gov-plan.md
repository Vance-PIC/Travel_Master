# Document Governance (Doc-Gov) Implementation Plan

## 1. Objective (目標)
建立專為大型知識庫與手冊量身打造的「文件審計工作流 (Doc-Gov)」。導入**「範本驅動」**與**「雙層審計機制」**，確保每個獨立章節的特有內容以及最終合併的整體文件都能獲得精確的品質控管。

## 2. Key Context (核心背景)
- 不同的章節類型（例如：財務預算表 vs. 每日行程表）需要不同的檢核邏輯。
- 文件合併後，可能出現內部連結斷裂或大綱結構不一致的問題，無法透過單一腳本涵蓋所有檢查。
- 專案已清除與程式碼開發相關的冗餘腳本。

## 3. Implementation Steps (實作步驟)

### Step 1: 建立雙層審計架構 (Dual-Layer Auditing)
將原本單一的 `audit-doc.ps1` 拆分並強化為兩支獨立腳本：
1.  **`scripts/audit-chapter.ps1` (章節級檢核)**：
    *   負責掃描 `src/*.md`。
    *   檢查基本紀律：無 `(略)` 或 `...` 等省略符號。
    *   **進階擴充**：支援讀取各章節專屬的檢核規則（如：D1 必須有預算表、D2 必須有行程表）。
2.  **`scripts/audit-global.ps1` (總體級檢核)**：
    *   在文件合併為 `OUTPUT.md` 後執行。
    *   檢查跨章節的錨點連結 (Anchor Links) 是否失效。
    *   檢查整體標題層次 (H1 -> H2 -> H3) 是否合理，避免排版斷層。

### Step 2: 重新定義 D1~D5 階段矩陣
| 階段 | 名稱 | 目標 | 物理產出/執行動作 |
| :--- | :--- | :--- | :--- |
| **D1** | **Context (背景與限制)** | 確立文件的「靈魂」：目標讀者是誰？核心目標為何？有哪些寫作限制（如語氣、字數）？以及特殊章節的檢核規則。 | `context.md` |
| **D2** | **Structure (章節拆分)** | 根據範本將手冊拆分為多個 `.md` 檔案。 | `outline.md` |
| **D3** | **Authoring (內容撰寫)** | 依照範本進行撰寫，全量展開。 | `src/*.md` |
| **D4** | **Chapter Audit (章節檢核)** | 針對各章節內容特徵與完整性進行審查。 | `audit-chapter.ps1` |
| **D5** | **Merge & Global Audit** | 合併章節，並執行全域格式與死連結檢查。 | `merge-doc.ps1` -> `audit-global.ps1` |

### Step 3: 更新專案治理配置
- 覆寫 `GEMINI.md`，注入雙層審計核心紀律。
- 更新 `conductor/doc-workflow.md`，展示新的五階段矩陣。

## 4. 驗證方式
- 分別執行 `audit-chapter.ps1` 檢查目前的 `src/01~08.md`。
- 執行合併並使用 `audit-global.ps1` 檢查 `OUTPUT.md` 的整體排版。

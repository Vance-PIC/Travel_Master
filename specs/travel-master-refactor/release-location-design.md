# 🛠️ 旅行大師發布手冊路徑優化設計規格書

- **設計日期**：2026-06-02
- **設計方案**：方案 B (發布手冊置於各自 specs 資料夾，且保留行程後綴)

---

## 📋 變更詳情 (Change Specification)

### 1. 腳本重構 `scripts/merge-doc.ps1`
- 修改產出路徑邏輯：
  - 熊本行程（kumamoto）：產出至 `specs/kumamoto/RELEASE.md`
  - 日本縱貫（japan-march）：產出至 `specs/japan-march/RELEASE-japan-march.md`
- 新增向後相容回退邏輯，若 `specs/[Spec]` 目錄不存在，仍回退輸出至專案根目錄下。

### 2. 物理搬遷與清理 (Cleanup)
- 刪除根目錄的舊發布檔：`RELEASE.md`、`RELEASE-japan-march.md`。
- 重新執行 `merge-doc.ps1` 在新目標路徑產出對應的發布檔。

### 3. 進度看板更新 `conductor/overview.md`
- 將備註說明中提及發布手冊的路徑更新為新路徑。

---
*本設計規格書遵循 Document Governance 治理架構存檔。*

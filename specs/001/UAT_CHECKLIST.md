# UAT Checklist: Track 001 - 拆分熊本旅遊手冊

## 驗收標準 (Acceptance Criteria)

### 1. 檔案存在驗證 (Physical Existence)
- [x] `src/01_Chapter1_核心戰報與財務預算.md` 已建立。
- [x] `src/02_Day1_抵達熊本.md` 已建立。
- [x] `src/03_Day2_熊本城巡禮.md` 已建立。
- [x] `src/04_Day3_Greenland全日遊.md` 已建立。
- [x] `src/05_Day4_挺進阿蘇.md` 已建立。
- [x] `src/06_Day5_農場深度玩與和牛烤肉.md` 已建立。
- [x] `src/07_Day6_阿蘇神社巡禮.md` 已建立。
- [x] `src/08_Day7_機場最後衝刺.md` 已建立。

### 2. 內容完整性驗證 (Content Integrity)
- [x] 每個檔案的第一行應為對應章節的標題。
- [x] 每個檔案的表格格式正確，無損壞。
- [x] 檔案內容與原始手冊對應章節 100% 一致。
- [x] 無任何 `(略)` 或內容遺失。

### 3. 系統規範驗證 (Standards Compliance)
- [x] 檔案編碼為 UTF-8 (No BOM)。
- [x] 原始手冊檔案保持不變。
- [x] 成功通過 `scripts/30_gate-preflight-check.ps1`。

---
**測試結果**: [PASS]
**測試日期**: 2026-05-14
**測試員**: Gemini CLI

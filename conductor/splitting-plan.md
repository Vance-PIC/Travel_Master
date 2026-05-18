# 章節拆分計畫：熊本旅遊作戰手冊 (V23.27 基準)

本計畫依照 `travel-manual-schema.md` 之範本結構，對 `V23.27` 版本執行物理拆分。

## 1. 物理檔案對照表 (Physical Mapping)

| 序號 | 檔案名稱 (src/) | 來源章節 | 預計狀態 |
| :-- | :--- | :--- | :--- |
| 01 | `01_Chapter1_核心戰報與財務預算.md` | 第一章 | `[D1 Context Check]` |
| 02 | `02_Day1_抵達熊本與櫻町放電.md` | 第二章 / Day 1 | `[D1 Context Check]` |
| 03 | `03_Day2_熊本城巡禮與領車任務.md` | 第二章 / Day 2 | `[D1 Context Check]` |
| 04 | `04_Day3_Greenland全日遊.md` | 第二章 / Day 3 | `[D1 Context Check]` |
| 05 | `05_Day4_挺進阿蘇與農場探險.md` | 第二章 / Day 4 | `[D1 Context Check]` |
| 06 | `06_Day5_農場深度玩與和牛烤肉.md` | 第二章 / Day 5 | `[D1 Context Check]` |
| 07 | `07_Day6_阿蘇神社與採果大慶功.md` | 第二章 / Day 6 | `[D1 Context Check]` |
| 08 | `08_Day7_機場最後衝刺.md` | 第二章 / Day 7 | `[D1 Context Check]` |

---

## 2. 初始品質掃描 (Initial Quality Scan - V23.27)

基於範本規格，初次掃描發現以下「內容缺口」：

### A. 嚴重缺口 (Blockers)
- **神隊友提醒缺失**：Day 2、Day 3、Day 5、Day 6、Day 7 均未包含「💡 神隊友提醒」或「🤝 重點筆記」模組。
- **預算明細未拆解**：Chapter 1 中的「OMO5 熊本 (3晚)」仍為合併計算法。
- **必備模組缺失**：Day 5~7 缺少「🛍️ 今日購物攻略」與「🏟️ 推薦景點表」。

### B. 警告缺口 (Warnings)
- **美食定量不足**：
  - Day 2：午餐 (1筆)、晚餐 (1筆) 等均未達 3-5 筆建議量。
  - Day 3：晚餐 (1筆)、宵夜 (1筆)。
  - Day 5~7：餐點推薦數量嚴重不足。

## 3. 下一步行動 (Next Steps)
1. 執行物理檔案寫入。
2. 進入 D4 審計，產出正式的「合規性紅綠燈報告」。

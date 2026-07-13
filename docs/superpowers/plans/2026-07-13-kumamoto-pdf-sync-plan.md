# 2026 熊本阿蘇 7 日行程 PDF 同步實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 `specs/kumamoto/src/` 底下的 8 個每日行程與守則 markdown 檔案（Chapter 2, Day 1 - Day 7）完全更新，使其符合最新版 PDF 行程安排，並在每次修改後通過格式與防雷審計（PASS）後執行 Git Commit。

**Architecture:** 
1. 採用「一章一存、逐檔稽核」策略。
2. 對照 PDF 的 OCR 文字，在 `src/` 對應檔案中更新行程表、美食地圖、購物攻略、景點表與神隊友提醒。
3. 所有更新需符合 `travel-manual-schema` 的禁菸標註、超連結與距離標註。
4. 每修改完一個檔案，即在 shell 執行 `scripts/audit-src.ps1`，確保該檔案全綠通過，隨後進行 Conventional Commit。

**Tech Stack:** Markdown, PowerShell, Git

---

### Task 1: 調整第二章作戰中心
**Files:**
- Modify: `specs/kumamoto/src/02_Chapter2_每日詳細作戰中心.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Chapter 2 檔案內容**
  依據 PDF 第 4 頁內容更新 `specs/kumamoto/src/02_Chapter2_每日詳細作戰中心.md`。
  將內容替換為：
  ```markdown
  # 第二章：每日詳細作戰中心 (Day 1 - Day 7)

  [🏠 返回總目錄](./00_Index.md)

  [⬅️ 上一頁 (第一章)](./01_Chapter1_核心戰報與財務預算.md) | [➡️ 下一頁 (Day 1)](./02.01_Day1_抵達熊本與櫻町放電.md)

  本章節將 7 天行程拆解為獨立的作戰指令，包含「職人級」的時間精算、動線導航與防雷提醒，確保全家在盂蘭盆節期間依然能優雅穿梭。

  ---

  #### **🤝 神隊友提醒**
  在進入每日行程前，請爸爸記住以下黃金守則：

  * **支付戰術**：熊本市區交通（市電/巴士）全面改用「信用卡感應」或「現金」，Suica 僅供販賣機與超商使用。⚠️ 禁菸車/全館禁菸。
  * **退稅死線**：多數商場（如 AMU, 鶴屋）退稅櫃台於 19:30 或 20:00 準時關閉，建議提前一小時結帳。
  * **水分補給**：8 月熊本極熱，請善用「阿蘇望之鄉」等景點補給阿蘇伏流水。

  ---

  ### 📅 快速跳轉：每日任務
  * [Day 1：抵達熊本與櫻町放電](./02.01_Day1_抵達熊本與櫻町放電.md)
  * [Day 2：熊本城巡禮與領車任務](./02.02_Day2_熊本城巡禮與領車任務.md)
  * [Day 3：Greenland 全日遊](./02.03_Day3_Greenland全日遊.md)
  * [Day 4：挺進阿蘇與農場探險](./02.04_Day4_挺進阿蘇與農場探險.md)
  * [Day 5：農場深度玩與和牛烤肉](./02.05_Day5_農場深度玩與和牛烤肉.md)
  * [Day 6：阿蘇神社與採果大慶功](./02.06_Day6_阿蘇神社與採果大慶功.md)
  * [Day 7：機場最後衝刺](./02.07_Day7_機場最後衝刺.md)

  ---
  [⬅️ 上一頁 (第一章)](./01_Chapter1_核心戰報與財務預算.md) | [➡️ 下一頁 (Day 1)](./02.01_Day1_抵達熊本與櫻町放電.md)

  [🏠 返回總目錄](./00_Index.md)
  ```

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Chapter 2 顯示 `[OK]`。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02_Chapter2_每日詳細作戰中心.md
  git commit -m "feat(docs): ch2 更新作戰中心黃金守則"
  ```

---

### Task 2: 調整 Day 1 行程與買鞋分工
**Files:**
- Modify: `specs/kumamoto/src/02.01_Day1_抵達熊本與櫻町放電.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Day 1 檔案內容**
  根據 PDF 頁面 5-7，將航班起飛時間更改為 `07:30 - 10:45`，更新空港特快巴士班次、熊本熊廣場分工，並將晚餐改為勝烈亭新市街本店，取消首日唐吉訶德。
  美食地圖中，將勝烈亭的備註修改為新市街本店。
  更新 `specs/kumamoto/src/02.01_Day1_抵達熊本與櫻町放電.md` 內容。

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Day 1 顯示 `[OK]`，美食與防雷規則全數通過。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02.01_Day1_抵達熊本與櫻町放電.md
  git commit -m "feat(docs): day1 更新航班、買鞋分工與晚餐勝烈亭新市街本店"
  ```

---

### Task 3: 調整 Day 2 熊本城與領車
**Files:**
- Modify: `specs/kumamoto/src/02.02_Day2_熊本城巡禮與領車任務.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Day 2 檔案內容**
  根據 PDF 頁面 8-10，早餐改為 OMO5 早餐（不安排 Komeda），行程表刪除魯夫銅像與 GiGO 遊戲中心，將取車時間提早至 17:40 - 18:00。
  更新 `specs/kumamoto/src/02.02_Day2_熊本城巡禮與領車任務.md` 內容。

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Day 2 顯示 `[OK]`。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02.02_Day2_熊本城巡禮與領車任務.md
  git commit -m "feat(docs): day2 早餐改OMO5，刪除魯夫銅像與GiGO，更新取車時間"
  ```

---

### Task 4: 調整 Day 3 Greenland 全日遊與麵包採買
**Files:**
- Modify: `specs/kumamoto/src/02.03_Day3_Greenland全日遊.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Day 3 檔案內容**
  根據 PDF 頁面 11-13，早上增加 07:30 - 08:30 步行至 Angelus 麵包採購排程，晚餐提早，並於 20:00 - 20:45 安排全家逛下通唐吉訶德。
  更新 `specs/kumamoto/src/02.03_Day3_Greenland全日遊.md` 內容。

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Day 3 顯示 `[OK]`。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02.03_Day3_Greenland全日遊.md
  git commit -m "feat(docs): day3 新增Angelus麵包採購與唐吉訶德逛街時段"
  ```

---

### Task 5: 調整 Day 4 Workman 交流道店與挺進阿蘇
**Files:**
- Modify: `specs/kumamoto/src/02.04_Day4_挺進阿蘇與農場探險.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Day 4 檔案內容**
  根據 PDF 頁面 15-17，Workman 改為「熊本交流道店」(更新 MapCode `29 649 78908`)，阿蘇望之鄉 MapCode 調整為 `256 215 727`。草千里與農場動物王國時間對齊（16:00 入場，16:30 截止）。
  更新 `specs/kumamoto/src/02.04_Day4_挺進阿蘇與農場探險.md` 內容。

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Day 4 顯示 `[OK]`。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02.04_Day4_挺進阿蘇與農場探險.md
  git commit -m "feat(docs): day4 更新Workman熊本交流道店及阿蘇望之鄉MapCode"
  ```

---

### Task 6: 調整 Day 5 農場與自炊
**Files:**
- Modify: `specs/kumamoto/src/02.05_Day5_農場深度玩與和牛烤肉.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Day 5 檔案內容**
  根據 PDF 頁面 18-20，元氣之森退房精細化。行程表新增「元氣挑戰館」與「手作體驗館 DIY」兩大行程。晚上新增阿蘇神社/門前町夜間散步行程。
  更新 `specs/kumamoto/src/02.05_Day5_農場深度玩與和牛烤肉.md` 內容。

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Day 5 顯示 `[OK]`。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02.05_Day5_農場深度玩與和牛烤肉.md
  git commit -m "feat(docs): day5 新增元氣挑戰館、手作DIY與神社夜間散步"
  ```

---

### Task 7: 調整 Day 6 阿蘇神社參拜與提前還車大慶功
**Files:**
- Modify: `specs/kumamoto/src/02.06_Day6_阿蘇神社與採果大慶功.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Day 6 檔案內容**
  根據 PDF 頁面 21-23，取消原「果實之國 COCORO」採果行程。早上改為阿蘇神社與門前町參拜/早午餐。下午安排 AEON 大津店與索隆像。17:00 還車（熊本機場店），爸爸搭計程車回大津飯店會合。晚餐於大津「燒肉鍋島」大慶功，隨後衝刺「HI Hirose」超級商場。
  更新 `specs/kumamoto/src/02.06_Day6_阿蘇神社與採果大慶功.md` 內容。

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Day 6 顯示 `[OK]`。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02.06_Day6_阿蘇神社與採果大慶功.md
  git commit -m "feat(docs): day6 取消採果行程，調整為D6下午還車、燒肉鍋島大慶功與HI Hirose掃貨"
  ```

---

### Task 8: 調整 Day 7 直達機場與返台
**Files:**
- Modify: `specs/kumamoto/src/02.07_Day7_機場最後衝刺.md`
- Audit script: `scripts/audit-src.ps1`

- [ ] **Step 1: 修改 Day 7 檔案內容**
  根據 PDF 頁面 24-26，因已提前還車，早上由大津飯店搭乘計程車直達機場。出境改為 JX847 `11:55 - 13:20` 起飛。
  更新 `specs/kumamoto/src/02.07_Day7_機場最後衝刺.md` 內容。

- [ ] **Step 2: 執行本地審計**
  Run: `powershell -File scripts/audit-src.ps1`
  Expected: Day 7 顯示 `[OK]`，且全部行程皆已通過。

- [ ] **Step 3: 執行 Git Commit**
  Run:
  ```bash
  git add specs/kumamoto/src/02.07_Day7_機場最後衝刺.md
  git commit -m "feat(docs): day7 改由計程車前往機場，更新起飛時間為11:55"
  ```

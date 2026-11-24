# Project WBS & Tracks Registry (旅行大師 Edition)

> **專案名稱**: 2027 名古屋 7 日親子自由行：旅遊指南
> **治理協議**: Doc-Gov D1~D5 + Git-Flow Step 1~8

---

## 📂 I. 工作分解結構 (WBS)

### **L1: 2027 名古屋親子手冊專案**
*   **L2 - D1: 背景與事實定錨 (Context)** ✅
*   **L2 - D2: 結構規格與範本 (Schema)** ✅
*   **L2 - D3: 物理原子拆分 (Splitting)** ✅
*   **L2 - D4: 內容精鍊循環 (Authoring - 執行中)**
    *   [x] **WP-00: 00_Index 總目錄索引** (Step 8)
    *   [x] **WP-01: Chapter 1 行程總覽與預算** (Step 8)
    *   [x] **WP-02: Chapter 2 每日行程總覽** (Step 8)
    *   [x] **WP-03: Day 1 抵達名古屋** (Step 8)
    *   [x] **WP-04: Day 2 LEGOLAND 生日慶典與積木奇幻日** (Step 8)
    *   [x] **WP-05: Day 3 榮商圈與名古屋站飛騨牛** (Step 8)
    *   [x] **WP-06: Day 4 東山動植物園** (Step 8)
    *   [x] **WP-07: Day 5 科學館與大須** (Step 8)
    *   [x] **WP-08: Day 6 熱田神宮與水族館** (Step 8)
    *   [x] **WP-09: Day 7 常滑與返台** (Step 8)
    *   [x] **WP-10: Chapter 3 行李準備與打包清單** (Step 8)
*   **L2 - D5: 全域整合與發布 (Release)** ✅
    *   [x] **WP-11: D5 全域整合發布** (Step 8)

---

## 🖋️ II. D micro-Tracks 實時狀態 (截至 2026-11-20)

| ID | 任務章節 | 座標 | 狀態 | 審計 | 核心精鍊紀錄 |
| :-- | :--- | :--- | :--- | :--- | :--- |
| 00 | 00_Index 總目錄 | **Step 8** | [DONE] | ✅ PASS | 已對齊 00_MASTER_INDEX 範本並補上 Ch3 索引。 |
| 01 | Ch1 總覽與預算 | **Step 8** | [DONE] | ✅ PASS | 已補齊住宿預算項目、Agoda 確認單細節、修正「待核訂單」並補行前提醒。 |
| 02 | Ch2 每日總覽 | **Step 8** | [DONE] | ✅ PASS | 已對齊 02_DAILY_OPERATIONS 範本、補齊交通/住宿欄與快速跳轉索引。 |
| 03 | Day 1 抵達名古屋 | **Step 8** | [DONE] | ✅ PASS | D1 修訂：中部國際空港名鐵窗口辦小兒 manaca、購買 μticket，經金山轉名城線至久屋大通，入住後吃拉麵。 |
| 04 | Day 2 LEGOLAND | **Step 8** | [DONE] | ✅ PASS | 已更名生日慶典、補 14 項遊樂設施、5 家園區商店、身高解鎖與車資。 |
| 05 | Day 3 榮商圈 | **Step 8** | [DONE] | ✅ PASS | 已補 Google Map、離飯店距離、7 欄購物表、伏見屋免手續費訂位管道與地鐵車資。 |
| 06 | Day 4 東山動植物園 | **Step 8** | [DONE] | ✅ PASS | 已潤稿定案、補動物園亮點（夏巴尼／清正／小熊貓）與 7 項遊樂園設施。 |
| 07 | Day 5 科學館大須 | **Step 8** | [DONE] | ✅ PASS | 已潤稿定案、錯開早餐首選，補星象儀 0 元座位票與大須動線。 |
| 08 | Day 6 熱田與水族館 | **Step 8** | [DONE] | ✅ PASS | 已整合 LaLaport 與 Workman、熱田／水族館亮點表演，補齊最後一晚晚餐備選。 |
| 09 | Day 7 常滑返台 | **Step 8** | [DONE] | ✅ PASS | 已補常滑招財貓、機場「風の湯」泡湯與 2026/11 免稅退稅順序。 |
| 10 | Ch3 行李打包清單 | **Step 8** | [DONE] | ✅ PASS | 已依 03_PACKING_CHECKLIST 範本完成初版（小紅卡、7 月避暑裝備、免稅規定）。 |
| 11 | D5 全域整合發布 | **Step 8** | [DONE] | ✅ PASS | 已執行 `merge-doc.ps1 -Spec nagoya-2027` 產出 `RELEASE-nagoya-2027.md`。 |

---
**本看板由『旅行大師』物理更新，確保流程合規。**

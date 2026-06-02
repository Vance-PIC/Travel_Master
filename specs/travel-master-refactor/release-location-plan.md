# 🛠️ 旅行大師發布路徑調整實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 `merge-doc.ps1` 合併發布的手冊存放在各自 specs 下，刪除根目錄發布檔，並更新 overview 看板連結。

**Architecture:** 
1. 重構 `scripts/merge-doc.ps1` 更改手冊輸出目錄。
2. 刪除根目錄 `RELEASE.md` 與 `RELEASE-japan-march.md`。
3. 修改 `conductor/overview.md` 的發布路徑說明。

**Tech Stack:** PowerShell, Markdown

---

### Task 1: 重構 `scripts/merge-doc.ps1` 的輸出路徑

**Files:**
- Modify: `scripts/merge-doc.ps1`

- [x] **Step 1: 修改 `scripts/merge-doc.ps1` 檔名與路徑解析邏輯**
  將 `scripts/merge-doc.ps1` 的路徑解析區塊修改為：
  ```powershell
  if ($OutputFile -eq "") {
      if ($Spec -eq "kumamoto") {
          $OUTPUT_FILE = Join-Path $ROOT_DIR "specs/kumamoto/RELEASE.md"
      } else {
          $OUTPUT_FILE = Join-Path $ROOT_DIR "specs/$Spec/RELEASE-$Spec.md"
      }
      
      # 向後相容回退
      if (-not (Test-Path (Join-Path $ROOT_DIR "specs/$Spec"))) {
          if ($Spec -eq "kumamoto") {
              $OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE.md"
          } else {
              $OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE-$Spec.md"
          }
      }
  } else {
      $OUTPUT_FILE = Join-Path $ROOT_DIR $OutputFile
  }
  ```

- [x] **Step 2: 執行熊本行程合併測試**
  執行命令：
  ```powershell
  pwsh -NoProfile -Command "chcp 65001; ./scripts/merge-doc.ps1 -Spec kumamoto"
  ```
  Expected: 成功在 `specs/kumamoto/RELEASE.md` 產生合併檔案。

- [x] **Step 3: 執行日本東西行軍行程合併測試**
  執行命令：
  ```powershell
  pwsh -NoProfile -Command "chcp 65001; ./scripts/merge-doc.ps1 -Spec japan-march"
  ```
  Expected: 成功在 `specs/japan-march/RELEASE-japan-march.md` 產生合併檔案。

- [x] **Step 4: Git Checkpoint 1**
  ```bash
  git add scripts/merge-doc.ps1 specs/kumamoto/RELEASE.md specs/japan-march/RELEASE-japan-march.md
  git commit -m "feat(scripts): output spec release files into specs subdirectory"
  ```

---

### Task 2: 物理清理舊版根目錄發布手冊

**Files:**
- Delete: `RELEASE.md`
- Delete: `RELEASE-japan-march.md`

- [x] **Step 1: 刪除根目錄發布手冊**
  執行命令：
  ```powershell
  Remove-Item -Path "RELEASE.md", "RELEASE-japan-march.md" -ErrorAction SilentlyContinue
  ```
  Expected: 根目錄下的兩個檔案已被刪除。

- [x] **Step 2: Git Checkpoint 2**
  ```bash
  git rm RELEASE.md RELEASE-japan-march.md
  git commit -m "cleanup(global): remove legacy release manuals from workspace root"
  ```

---

### Task 3: 更新全域進度總覽看板

**Files:**
- Modify: `conductor/overview.md`
- Modify: `specs/travel-master-refactor/release-location-plan.md` (本計畫本身打勾)

- [x] **Step 1: 修改 `conductor/overview.md` 的路徑標記**
  將 `conductor/overview.md` 內容中的 `已產出 RELEASE.md` 說明文字與連結更新，使其對齊新發布路徑。

- [x] **Step 2: Git Checkpoint 3**
  ```bash
  git add conductor/overview.md specs/travel-master-refactor/release-location-plan.md
  git commit -m "docs(global): update overview manual locations"
  ```

# 「旅行大師 (Travel-Master)」專案重構實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將專案重構為「旅行大師」多行程並存架構，將熊本與日本東西行軍行程收納至 specs 目錄，重構全域自動化腳本 audit-src, sync-tracks, merge-doc 支援 -Spec 參數，並建立全域進度總覽看板。

**Architecture:** 
1. 資料夾更名與搬遷：將 src, conductor 中的行程內容搬移到 specs/[spec_name]/src，並將 references 移動到 specs/[spec_name]/references/。
2. 腳本重構：在 scripts/ 中的 PowerShell 腳本頂部加入 [string]$Spec = "kumamoto" 參數，動態解析路徑，並提供向下相容（若找不到新路徑則使用根目錄的 src 與 conductor）。
3. 看板與原則修訂：在 conductor/ 建立全域進度總覽 overview.md，並修改 GEMINI.md 以定義新的結構規範。

**Tech Stack:** PowerShell, Markdown

---

### Task 1: 建立新目錄結構與搬遷熊本行程檔案

**Files:**
- Create: `specs/kumamoto/src/`
- Create: `specs/kumamoto/references/`
- Modify: 移動現有熊本行程檔案至新位置。

- [x] **Step 1: 建立熊本新目錄結構**
  執行命令以建立 `specs/kumamoto/src/` 和 `specs/kumamoto/references/` 目錄：
  ```powershell
  New-Item -ItemType Directory -Force -Path "specs/kumamoto/src"
  New-Item -ItemType Directory -Force -Path "specs/kumamoto/references"
  ```
  Expected: 目錄成功建立。

- [x] **Step 2: 搬移熊本行程章節內容 (src)**
  將原根目錄下 `src/` 的所有 Markdown 檔案搬移至 `specs/kumamoto/src/`：
  ```powershell
  Move-Item -Path "src/*.md" -Destination "specs/kumamoto/src/" -Force
  ```
  Expected: 原 `src/` 下的所有檔案順利移至 `specs/kumamoto/src/`。隨後物理刪除原 `src/` 資料夾：
  ```powershell
  Remove-Item -Path "src" -Recurse -Force
  ```

- [x] **Step 3: 搬移熊本專屬參考資料 (references)**
  將根目錄下的 `熊本之旅行程表.pdf`、`熊本行程表.pdf` 與 `熊本之旅行程表.md` 移動至 `specs/kumamoto/references/`：
  ```powershell
  Move-Item -Path "熊本之旅行程表.pdf", "熊本行程表.pdf", "熊本之旅行程表.md" -Destination "specs/kumamoto/references/" -Force
  ```
  Expected: 參考資料搬移成功。

- [x] **Step 4: 建立熊本專屬 conductor 目錄與搬遷看板**
  建立 `conductor/kumamoto/` 目錄並移動原 `conductor/` 下的 `doc-tracks.md` 與 `progress_report.md`：
  ```powershell
  New-Item -ItemType Directory -Force -Path "conductor/kumamoto"
  Move-Item -Path "conductor/doc-tracks.md" -Destination "conductor/kumamoto/doc-tracks.md" -Force
  Move-Item -Path "conductor/progress_report.md" -Destination "conductor/kumamoto/progress_report.md" -Force
  ```
  Expected: 熊本專屬看板檔案順利就位。

- [x] **Step 5: Git Checkpoint 1**
  ```bash
  git add specs/kumamoto conductor/kumamoto
  git commit -m "refactor(kumamoto): move kumamoto files to specs/kumamoto and conductor/kumamoto"
  ```

---

### Task 2: 搬遷日本東西行軍行程檔案

**Files:**
- Create: `specs/japan-march/src/`
- Create: `specs/japan-march/references/`
- Modify: 搬移並整頓日本東西行軍行程檔案，並刪除冗餘目錄。

- [x] **Step 1: 建立日本東西行軍新目錄結構**
  執行命令以建立 `specs/japan-march/src` 與 `specs/japan-march/references` 目率：
  ```powershell
  New-Item -ItemType Directory -Force -Path "specs/japan-march/src"
  New-Item -ItemType Directory -Force -Path "specs/japan-march/references"
  ```

- [x] **Step 2: 搬移日本東西行軍章節內容 (src)**
  將 `日本東西行軍路線/src/` 下的所有 Markdown 檔案搬移至 `specs/japan-march/src/`：
  ```powershell
  Move-Item -Path "日本東西行軍路線/src/*.md" -Destination "specs/japan-march/src/" -Force
  ```

- [x] **Step 3: 搬移日本東西行軍專屬參考資料 (references)**
  將 `日本東西行軍路線/行軍之旅.zip` 移動至 `specs/japan-march/references/`：
  ```powershell
  Move-Item -Path "日本東西行軍路線/行軍之旅.zip" -Destination "specs/japan-march/references/" -Force
  ```

- [x] **Step 4: 建立行軍專屬 conductor 目錄與搬遷看板**
  建立 `conductor/japan-march/` 目錄並移動 `日本東西行軍路線/conductor/` 下的 `doc-tracks.md` 與 `progress_report.md`：
  ```powershell
  New-Item -ItemType Directory -Force -Path "conductor/japan-march"
  Move-Item -Path "日本東西行軍路線/conductor/doc-tracks.md" -Destination "conductor/japan-march/doc-tracks.md" -Force
  Move-Item -Path "日本東西行軍路線/conductor/progress_report.md" -Destination "conductor/japan-march/progress_report.md" -Force
  ```

- [x] **Step 5: 物理清理原行軍目錄**
  確認 `日本東西行軍路線/` 底下的 src, conductor 均已搬空，且其 scripts/ 和 knowledge/ 已無特別資產（全域共享已由根目錄接管），可將該目錄徹底刪除：
  ```powershell
  Remove-Item -Path "日本東西行軍路線" -Recurse -Force
  ```

- [x] **Step 6: Git Checkpoint 2**
  ```bash
  git add specs/japan-march conductor/japan-march
  git commit -m "refactor(japan-march): move japan-march files to specs/japan-march and conductor/japan-march"
  ```

---

### Task 3: 重構全域審計腳本 `scripts/audit-src.ps1`

**Files:**
- Modify: `scripts/audit-src.ps1`

- [x] **Step 1: 重構 `scripts/audit-src.ps1` 加入參數與動態路徑**
  將 `scripts/audit-src.ps1` 修改為支援 `-Spec` 參數，代碼如下：
  ```powershell
  # scripts/audit-src.ps1
  # [v1.5.0] Multi-Spec Support with Backward Compatibility
  
  param (
      [string]$Spec = "kumamoto"
  )
  
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
  $ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
  $ErrorCount = 0
  
  Write-Host "--- Start Audit for Spec: $Spec ---" -ForegroundColor Cyan
  
  # 動態定位行程 src 目錄，若 specs/ 下找不到則回退至根目錄的 src
  $SPEC_SRC_DIR = Join-Path $ROOT_DIR "specs/$Spec/src"
  if (-not (Test-Path $SPEC_SRC_DIR)) {
      $SPEC_SRC_DIR = Join-Path $ROOT_DIR "src"
  }
  
  if (-not (Test-Path $SPEC_SRC_DIR)) {
      Write-Host "FAIL: Source directory not found ($SPEC_SRC_DIR)" -ForegroundColor Red
      exit 1
  }
  
  $MdFiles = Get-ChildItem -Path $SPEC_SRC_DIR -Filter "*.md"
  foreach ($file in $MdFiles) {
      $fName = $file.Name
      $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
      
      # 1. Format Check
      if ($content -match "今日美食地圖") {
          if ($content -notmatch "今日美食地圖 \(定量推薦\)") {
              Write-Host "FAIL: $fName - Gourmet Map Header format error" -ForegroundColor Red
              $ErrorCount++
          }
      }
      
      if ($content -match "神隊友提醒" -and $content -notmatch "🤝 神隊友提醒") {
          Write-Host "FAIL: $fName - Reminder Icon error" -ForegroundColor Red
          $ErrorCount++
      }
  
      # 2. Content Check
      if ($content -match "\(略\)|（略）|\.\.\.") {
          Write-Host "FAIL: $fName - Omission detected" -ForegroundColor Red
          $ErrorCount++
      }
  
      if ($fName -match "Day") {
          $cats = @("早", "午", "晚", "品")
          foreach ($cat in $cats) {
              $m = [regex]::Matches($content, "(?m)^\|\s*$cat\s*\|")
              if ($m.Count -lt 3) {
                  Write-Host "FAIL: $fName - $cat category only has $($m.Count) items" -ForegroundColor Red
                  $ErrorCount++
              }
          }
      }
  }
  
  if ($ErrorCount -eq 0) {
      Write-Host "--- Audit PASS ($Spec) ---" -ForegroundColor Green
      exit 0
  } else {
      Write-Host "--- Audit FAILED: $ErrorCount errors ---" -ForegroundColor Red
      exit 1
  }
  ```

- [x] **Step 2: 執行熊本行程審計測試**
  執行命令：
  ```powershell
  ./scripts/audit-src.ps1 -Spec kumamoto
  ```
  Expected: 輸出 `--- Audit PASS (kumamoto) ---`。

- [x] **Step 3: 執行日本行軍行程審計測試**
  執行命令：
  ```powershell
  ./scripts/audit-src.ps1 -Spec japan-march
  ```
  Expected: 輸出 `--- Audit PASS (japan-march) ---`。

- [x] **Step 4: Git Checkpoint 3**
  ```bash
  git add scripts/audit-src.ps1
  git commit -m "feat(scripts): add multi-spec support to audit-src.ps1"
  ```

---

### Task 4: 重構全域同步腳本 `scripts/sync-tracks.ps1`

**Files:**
- Modify: `scripts/sync-tracks.ps1`

- [x] **Step 1: 重構 `scripts/sync-tracks.ps1` 加入參數與動態看板路徑**
  將 `scripts/sync-tracks.ps1` 修改為支援 `-Spec` 參數，代碼如下：
  ```powershell
  # scripts/sync-tracks.ps1
  # [v1.2.0] Multi-Spec Progress Sync
  
  param (
      [string]$WP_ID = "",
      [Parameter(Mandatory=$true)]
      [string]$Status,
      [string]$Message = "",
      [string]$Spec = "kumamoto"
  )
  
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
  
  # 動態定位看板檔案
  $TRACKS_FILE = Join-Path $ROOT_DIR "conductor/$Spec/doc-tracks.md"
  $REPORT_FILE = Join-Path $ROOT_DIR "conductor/$Spec/progress_report.md"
  
  # 向後相容回退
  if (-not (Test-Path $TRACKS_FILE)) {
      $TRACKS_FILE = Join-Path $ROOT_DIR "conductor/doc-tracks.md"
      $REPORT_FILE = Join-Path $ROOT_DIR "conductor/progress_report.md"
  }
  
  if (-not (Test-Path $TRACKS_FILE)) { Write-Host "Tracks file not found at $TRACKS_FILE"; exit 1 }
  $tracksContent = Get-Content $TRACKS_FILE -Raw -Encoding UTF8
  
  # --- Auto Detect ---
  if ($WP_ID -eq "") {
      $regexDetect = "(?m)^\|\s*(\d{2})\s*\|.*?(?:\[TRACKING\]|\[IN REVIEW\])"
      if ($tracksContent -match $regexDetect) {
          $WP_ID = $matches[1]
          Write-Host "Auto-detected WP-$WP_ID"
      } else {
          Write-Host "No active track found to sync"
          exit 1
      }
  }
  
  # --- Map status ---
  $step = "Step 0"
  $stat = "[PENDING]"
  $audit = "⏳ PENDING"
  
  if ($Status -eq "TRACKING") { $step = "Step 2"; $stat = "[TRACKING]"; $audit = "⏳ PENDING" }
  elseif ($Status -eq "REVIEW") { $step = "Step 7"; $stat = "[IN REVIEW]"; $audit = "⏳ PENDING" }
  elseif ($Status -eq "DONE") { $step = "Step 8"; $stat = "[DONE]"; $audit = "✅ PASS" }
  
  # --- Update doc-tracks.md ---
  $lineRegex = "(?m)^\|\s*$WP_ID\s*\|(.*?)\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|"
  if ($tracksContent -match $lineRegex) {
      $oldLine = $matches[0]
      $chapter = $matches[1].Trim()
      $memo = $matches[4].Trim()
      if ($Message -ne "") { $memo = $Message }
      $newLine = "| $WP_ID | $chapter | **$step** | $stat | $audit | $memo |"
      $tracksContent = $tracksContent -replace [regex]::Escape($oldLine), $newLine
      $tracksContent | Set-Content $TRACKS_FILE -Encoding UTF8
      Write-Host "Updated doc-tracks.md for Spec: $Spec, WP-$WP_ID"
  }
  
  # --- Update progress_report.md ---
  $totalCount = ([regex]::Matches($tracksContent, "(?m)^\| \d{2} \|")).Count
  $doneCount = ([regex]::Matches($tracksContent, "\[DONE\]")).Count
  if ($totalCount -gt 0) {
      $pct = [math]::Round(($doneCount / $totalCount) * 100)
      if (Test-Path $REPORT_FILE) {
          $rep = Get-Content $REPORT_FILE -Raw -Encoding UTF8
          $rep = $rep -replace "總體進度】：\d+%", "總體進度】：$pct%"
          $rep = $rep -replace "\d+/\d+ 章節完工", "$doneCount/$totalCount 章節完工"
          $rep | Set-Content $REPORT_FILE -Encoding UTF8
          Write-Host "Updated progress_report.md to $pct% ($Spec)"
      }
  }
  Write-Host "Sync Complete"
  ```

- [x] **Step 2: 執行同步功能測試 (以日本東西行軍行程 Day 1 設為 REVIEW 為例)**
  執行命令：
  ```powershell
  ./scripts/sync-tracks.ps1 -Spec japan-march -WP_ID 03 -Status REVIEW -Message "待安排羽田➔橫濱/秋葉原交通與弄髮行程。"
  ```
  Expected: 輸出 `Updated doc-tracks.md for Spec: japan-march, WP-03`，並且 [conductor/japan-march/doc-tracks.md](file:///C:/Home/熊本旅遊實作/conductor/japan-march/doc-tracks.md) 的 WP-03 狀態變為 `[IN REVIEW]`。

- [x] **Step 3: Git Checkpoint 4**
  ```bash
  git add scripts/sync-tracks.ps1
  git commit -m "feat(scripts): add multi-spec support to sync-tracks.ps1"
  ```

---

### Task 5: 重構全域合併腳本 `scripts/merge-doc.ps1`

**Files:**
- Modify: `scripts/merge-doc.ps1`

- [x] **Step 1: 重構 `scripts/merge-doc.ps1` 支援多行程合併**
  將 `scripts/merge-doc.ps1` 修改為支援 `-Spec` 參數，以指向新路徑 `specs/$Spec/src`，並輸出到根目錄的 `RELEASE-$Spec.md` (或熊本行程維持預設 `RELEASE.md`)。代碼如下：
  ```powershell
  # merge-doc.ps1 - Document Merger (RELEASE Edition)
  # [v1.5.0] Multi-Spec Document Merger
  
  param (
      [string]$Spec = "kumamoto",
      [string]$TargetDir = "",
      [string]$OutputFile = ""
  )
  
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
  
  # 自適應探測根目錄
  $current = (Get-Item $PSScriptRoot)
  $ROOT_DIR = $null
  while ($current -ne $null) {
      if ((Test-Path (Join-Path $current.FullName "conductor")) -or (Test-Path (Join-Path $current.FullName "specs"))) {
          $ROOT_DIR = $current.FullName
          break
      }
      $current = $current.Parent
  }
  if ($null -eq $ROOT_DIR) {
      $ROOT_DIR = Resolve-Path "$PSScriptRoot\.."
  }
  
  # 動態路徑解析
  if ($TargetDir -eq "") {
      $SRC_DIR = Join-Path $ROOT_DIR "specs/$Spec/src"
      if (-not (Test-Path $SRC_DIR)) {
          $SRC_DIR = Join-Path $ROOT_DIR "src"
      }
  } else {
      $SRC_DIR = Join-Path $ROOT_DIR $TargetDir
  }
  
  if ($OutputFile -eq "") {
      if ($Spec -eq "kumamoto") {
          $OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE.md"
      } else {
          $OUTPUT_FILE = Join-Path $ROOT_DIR "RELEASE-$Spec.md"
      }
  } else {
      $OUTPUT_FILE = Join-Path $ROOT_DIR $OutputFile
  }
  
  Write-Host "`n[Merge] 啟動穩定錨點合併程序 (v25.00)..." -ForegroundColor Cyan
  Write-Host "  - 行程 Spec: $Spec"
  Write-Host "  - 來源路徑: $SRC_DIR"
  Write-Host "  - 輸出檔案: $OUTPUT_FILE"
  
  if (-not (Test-Path $SRC_DIR)) {
      Write-Host "錯誤: 找不到來源路徑 '$SRC_DIR'。" -ForegroundColor Red
      exit 1
  }
  
  $MdFiles = Get-ChildItem -Path $SRC_DIR -Filter "*.md" | Sort-Object Name
  if ($MdFiles.Count -eq 0) {
      Write-Host "警告: 來源路徑中無任何 Markdown 檔案。" -ForegroundColor Yellow
      exit 0
  }
  
  $FullContent = New-Object System.Text.StringBuilder
  
  foreach ($file in $MdFiles) {
      Write-Host "  - 正在處理: $($file.Name)"
      $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
      
      # 取得章節編號 (例如 01, 02...)
      if ($file.Name -match "^(\d{2})") {
          $chId = $matches[1]
          # 在章節最前方插入隱形錨點
          $content = "<div id='ch-$chId'></div>`n`n" + $content
      }
  
      # 1. 清理導航行 (只要行內包含 上一頁、下一頁 或 返回總目錄，整行徹底清除)
      $content = $content -replace '(?m)^.*?(上一頁|下一頁|返回總目錄).*?$', ''
  
      # 2. 連結校準 (指向穩定 ID)
      $content = $content -replace '\.\/(\d{2})_.*\.md', '#ch-$1'
      
      [void]$FullContent.AppendLine($content)
      [void]$FullContent.AppendLine("`n---`n")
  }
  
  # 3. 寫入檔案
  $finalText = $FullContent.ToString() -replace '(?m)^\s*$\n\s*$\n', "`n"
  [System.IO.File]::WriteAllText($OUTPUT_FILE, $finalText, $OutputEncoding)
  
  Write-Host ("-" * 50)
  Write-Host "[成功] 已產生穩定跳轉文件: $OUTPUT_FILE" -ForegroundColor Green
  ```

- [x] **Step 2: 測試熊本行程合併**
  執行命令：
  ```powershell
  ./scripts/merge-doc.ps1 -Spec kumamoto
  ```
  Expected: 成功合併並更新根目錄下的 [RELEASE.md](file:///C:/Home/熊本旅遊實作/RELEASE.md)。

- [x] **Step 3: 測試日本東西行軍行程合併**
  執行命令：
  ```powershell
  ./scripts/merge-doc.ps1 -Spec japan-march
  ```
  Expected: 成功合併並在根目錄下產生 `RELEASE-japan-march.md`。

- [x] **Step 4: Git Checkpoint 5**
  ```bash
  git add scripts/merge-doc.ps1
  git commit -m "feat(scripts): add multi-spec support to merge-doc.ps1"
  ```

---

### Task 6: 建立全域進度總覽 `conductor/overview.md` 與修訂 `GEMINI.md`

**Files:**
- Create: `conductor/overview.md`
- Modify: `GEMINI.md`

- [ ] **Step 1: 建立 `conductor/overview.md` 檔案**
  寫入以下內容到 `conductor/overview.md`：
  ```markdown
  # 🌐 旅行大師 (Travel-Master) 專案進度總覽
  
  本看板彙整全專案所有獨立行程（Specs）的當前進度與發布狀態。
  
  ---
  
  ## 📊 行程總覽 (Overview Registry)
  
  | 行程名稱 | 總章節數 | 已完工 (DONE) | 進度比例 | 當前狀態 | 備註說明 |
  | :--- | :---: | :---: | :---: | :--- | :--- |
  | [2026 熊本阿蘇 7 日親子自駕](file:///C:/Home/%E6%97%85%E8%A1%8C%E5%A4%A7%E5%B8%AB/conductor/kumamoto/doc-tracks.md) | 10 | 10 | 100% | ✅ DONE | 全案完工，已產出 RELEASE.md |
  | [2026 日本 12 日鐵道大縱貫](file:///C:/Home/%E6%97%85%E8%A1%8C%E5%A4%A7%E5%B8%AB/conductor/japan-march/doc-tracks.md) | 15 | 2 | 13% | ⏳ TRACKING | 目前正在精鍊 Day 1 行程 |
  
  ---
  *註：進度由『旅行大師』治理機制實時定錨維護。*
  ```

- [ ] **Step 2: 修訂 `GEMINI.md` 的目錄結構**
  更新 `GEMINI.md` 的目錄結構定義部分，與新結構保持一致：
  ```markdown
  ## 4. 目錄結構
  - `specs/[行程代號]/src/`: 各行程當前撰寫中的章節檔案 (唯一真理)。
  - `specs/[行程代號]/references/`: 各行程專屬的歷史版本與歷史行程表參考。
  - `knowledge/templates/`: 全域共享之寫作與 UAT 範本。
  - `knowledge/references/`: 全域共享之通用參考資料。
  - `scripts/`: 全域共享之自動化審計與進度同步腳本 (支援 -Spec 參數)。
  - `conductor/`: 全域共享之各行程任務進度看板。
    - `conductor/overview.md`: 全域行程進度總覽。
    - `conductor/[行程代號]/`: 各行程的 WBS 看板與進度狀態。
  ```

- [ ] **Step 3: Git Checkpoint 6**
  ```bash
  git add conductor/overview.md GEMINI.md
  git commit -m "docs(global): add overview registry and update GEMINI.md structure"
  ```

# GitHub Pages 公開價格儀表板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把現有名古屋監控的有效價格發布為公開、唯讀、無家庭私人資訊的 GitHub Pages 儀表板。

**Architecture:** Python 產生器只從私人 `Travel_Master` 的 `latest.json` 擷取白名單欄位，套入獨立的公開頁樣板，輸出 `_site/index.html`。發布 workflow 在現有監控完成、頁面來源變更或手動執行時，只把該 HTML 推至獨立公開儲存庫 `Vance-PIC/Travel_Master_Prices`（暫定名稱）的 `main` 根目錄，由其 GitHub Pages 發布；不呼叫查價 API，也不改監控排程。

**Tech Stack:** Python 3.12 標準函式庫、HTML/CSS、GitHub Actions、GitHub Pages。

**Spec:** `docs/superpowers/specs/2026-10-05-public-price-dashboard-design.md`

## Global Constraints

- 只公開航線、旅行日期、航空公司、航班號、飯店名稱、已觀測價格與資料時間；不公開逐日行程、旅客資訊、已訂房基準、家庭預算、原始 API 資料或密鑰。
- 只同步 `_site/index.html`；不得公開私人 `Travel_Master`、現有完整儀表板、原始 `travel/nagoya` 目錄或其他 `_site` 檔案。
- 使用私人 repo 的 `PUBLIC_PAGES_TOKEN` Actions secret 跨儲存庫寫入；權杖只授予公開目標 repo Contents read/write，不進入 URL、程式碼或日誌。未設定時發布失敗。
- 不新增查價呼叫、監控排程或修改 flight/hotel monitor policy。
- 未經當次 Booking Options 驗證，不得把 API 顯示價格稱為家庭總價；飯店保留原幣別，不自行換匯。
- 報價超過 48 小時標示過期，且每筆資料時間取該筆觀測值，不冒用頁面產生時間。

## Review Focus

- 缺少或損毀 `latest.json`：呈現無可用資料，產生器不可崩潰或發布私人除錯資訊。
- 不同時區或無效 `checked_at`：顯示原值或未知，不把發布時間當觀測時間。
- 價格為 `null`、字串或負數：不得進 Top 5 或顯示成有效價格。
- 供應商名稱含 HTML 特殊字元：以文字安全跳脫，不執行注入的 HTML/Script。
- 曾驗證但不屬於當次報價：不可沿用「已驗證家庭總價」標籤。

---

### Task 1: 資料白名單與價格語意

**Files:**
- Create: `scripts/build_public_dashboard.py`
- Create: `tests/test_public_dashboard.py`

**Interfaces:**
- Consumes: `travel/nagoya/flights/latest.json` 與 `travel/nagoya/hotels/*/latest.json`。
- Produces: `project_flights(snapshot: dict, now: datetime) -> list[dict]`、`project_hotels(hotel_dir: Path, now: datetime) -> list[dict]`。回傳值僅含允許公開的欄位。

- [ ] **Step 1: 寫失敗測試。** 建立最小快照：三筆不同價格的 itinerary，其中一筆 `price_scope=unknown`，一筆帶當次 `price_verification`，一筆價格無效；確認只留下兩筆並排序。驗證失效時即使 `family_total_twd` 有值，仍顯示未驗證。飯店樣本使用 `query_currency=JPY`，確認不轉為 TWD。

```python
def sample_flight_snapshot():
    return {"itineraries": [
        {"displayed_price_twd": 68466, "price_scope": "family_total",
         "family_total_twd": 68466, "checked_at": "2026-10-05T15:00:00+08:00",
         "price_verification": {"price": 68466, "verified_at": "2026-10-05T15:00:00+08:00",
                                "quote_checked_at": "2026-10-05T15:00:00+08:00"}},
        {"displayed_price_twd": 63090, "price_scope": "unknown",
         "family_total_twd": None, "checked_at": "2026-10-05T15:00:00+08:00"},
        {"displayed_price_twd": -1, "checked_at": "2026-10-05T15:00:00+08:00"},
    ]}

def test_project_flights_orders_and_preserves_scope():
    rows = project_flights(sample_flight_snapshot(), datetime(2026, 10, 5, 8, tzinfo=timezone.utc))
    assert [row["displayed_price_twd"] for row in rows] == [63090, 68466]
    assert rows[0]["price_label"] == "API 顯示價格，未驗證為家庭總價"
    assert rows[1]["price_label"] == "已驗證家庭總價"
    assert "passengers" not in str(rows)
```

- [ ] **Step 2: 執行 `python -m unittest tests.test_public_dashboard -v`，確認因尚無產生器而失敗。**
- [ ] **Step 3: 實作最小投影函式。** 用 `json`、`datetime`、`pathlib` 讀取資料。有效 itinerary 須有有限、非負的數值價格與自己的 `checked_at`；驗證條件為 `price_scope == "family_total"`、`family_total_twd == displayed_price_twd`、`price_verification.quote_checked_at == checked_at`、`price_verification.verified_at` 存在且 `price_verification.price == displayed_price_twd`。取 Top 5，但不修改原始快照或 history。飯店只取觀測價格、原幣別、名稱、日期、來源、觀測時間與既有驗證狀態。解析失敗回傳空清單及供公開顯示的簡短狀態，不輸出原始例外內容。
- [ ] **Step 4: 加入缺檔、損毀 JSON、無效價格、時區、過期（超過 48 小時）測試並執行 `python -m unittest tests.test_public_dashboard -v`。**
- [ ] **Step 5: `git add scripts/build_public_dashboard.py tests/test_public_dashboard.py`，提交 `feat: project monitor quotes for public dashboard`。**

### Task 2: 獨立的公開頁與隱私檢查

**Files:**
- Create: `site/public_price_template.html`
- Modify: `scripts/build_public_dashboard.py`
- Modify: `tests/test_public_dashboard.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 1 的投影結果。
- Produces: `render_page(flights: list[dict], hotels: list[dict], status: dict) -> str`，及 CLI `python scripts/build_public_dashboard.py --output _site`。

- [ ] **Step 1: 寫失敗測試。** 傳入 `"<script>alert(1)</script>"` 供應商名稱，確認輸出只有跳脫後的文字。用含孩子年齡、已訂房基準、家庭預算、逐日行程的樣本 JSON 建頁，確認 `_site/index.html` 不含這些值、原始 JSON 或 `SERPAPI_KEY` 等憑證名稱。確認顯示 `checked_at` 與「資料過期」，不是把頁面產生時間寫成報價時間。

```python
def test_public_html_escapes_and_omits_private_fields(tmp_path):
    html = render_page([{"airline": "<script>alert(1)</script>", "price_label": "API 顯示價格，未驗證為家庭總價"}], [], {})
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "child_ages" not in html
```

- [ ] **Step 2: 執行測試，確認缺少 `render_page` 等預期失敗。**
- [ ] **Step 3: 建立獨立 HTML 樣板。** 沿用舊 dashboard 的深藍／靛色、卡片及表格視覺，僅有機票與飯店區；透過 Python `html.escape` 插入白名單文字。不要嵌入原始 JSON、旅程規劃、靜態購票價格或第三方即時查價 JavaScript。CLI 只將 `index.html` 寫入 `_site`。

```python
from html import escape

def cell(value: object) -> str:
    return escape(str(value if value is not None else "—"), quote=True)

# render_page 僅把 Task 1 的白名單投影結果傳給 cell()，
# 再替換樣板內的 {{FLIGHT_ROWS}}、{{HOTEL_ROWS}}、{{STATUS}}。
```
- [ ] **Step 4: 執行測試及實際樣本產生：`python scripts/build_public_dashboard.py --output _site`。檢視產物與 `git diff --check`；`_site/` 應被 `.gitignore` 忽略。**
- [ ] **Step 5: 提交 `feat: render privacy-safe public price page`。**

### Task 3: 推送脫敏 HTML 至獨立公開 Pages 儲存庫

**Files:**
- Create: `.github/workflows/publish-price-dashboard.yml`
- Create: `docs/public-price-dashboard.md`
- Test: `tests/test_public_dashboard.py`

**Interfaces:**
- Consumes: Task 2 的 CLI 與預設分支監控快照。
- Produces: 公開儲存庫 `main` 根目錄的 `index.html`；不寫入 `latest.json` 或 history。

- [ ] **Step 1: 寫 workflow 測試。** 確認 workflow 含 `workflow_run`（監聽 `Nagoya SerpApi flight monitor`、`Hotel monitor executor` 的 `completed`）、`workflow_dispatch` 與僅針對頁面檔案的 `push`；確認沒有 `schedule`、`SERPAPI_KEY`、`SEARCHAPI_KEY`、`Ignav_KEY` 或查價腳本。確認缺少 `PUBLIC_PAGES_TOKEN` 時明確失敗，檢出限定的公開 repo，且只複製及暫存 `index.html`，不使用同 repo Pages artifact/deploy actions。

```python
def test_pages_workflow_has_no_fare_api_calls():
    workflow = Path(".github/workflows/publish-price-dashboard.yml").read_text(encoding="utf-8")
    assert "workflow_run:" in workflow and "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "repository: Vance-PIC/Travel_Master_Prices" in workflow
    assert "cp _site/index.html public-site/index.html" in workflow
    assert "git -C public-site add -- index.html" in workflow
    assert "actions/deploy-pages@" not in workflow
    for forbidden in ("SERPAPI_KEY", "SEARCHAPI_KEY", "Ignav_KEY", "nagoya_flight_monitor.py", "hotel_executor.py"):
        assert forbidden not in workflow
```
- [ ] **Step 2: 執行 `python -m unittest tests.test_public_dashboard -v`，確認新 workflow 測試先失敗。**
- [ ] **Step 3: 加入 workflow。** 只在預設分支的監控完成事件發布；`actions/checkout` 檢出私人 `master` 並停用持久憑證，Python 產生 `_site/index.html`，檢查 `PUBLIC_PAGES_TOKEN`，再以限定公開 repo 的 PAT 檢出其 `main`。只複製 `_site/index.html` 並 `git add -- index.html`，內容未變時略過 commit；變更時推送 `main`。設定私人 workflow `contents: read` 與 concurrency；不得讀取查價 secrets。文件說明公開欄位、手動重建、資料時間與隱私邊界。

```yaml
name: Publish public price dashboard
on:
  workflow_dispatch:
  push:
    branches: [master]
    paths:
      - 'scripts/build_public_dashboard.py'
      - 'site/public_price_template.html'
      - '.github/workflows/publish-price-dashboard.yml'
  workflow_run:
    workflows: ['Nagoya SerpApi flight monitor', 'Hotel monitor executor']
    types: [completed]
permissions:
  contents: read
jobs:
  publish:
    if: github.event_name != 'workflow_run' || github.event.workflow_run.head_branch == 'master'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: master
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python scripts/build_public_dashboard.py --output _site
      - name: Check public repository credential
        env:
          PUBLIC_PAGES_TOKEN: ${{ secrets.PUBLIC_PAGES_TOKEN }}
        run: |
          if [ -z "$PUBLIC_PAGES_TOKEN" ]; then
            echo 'PUBLIC_PAGES_TOKEN is missing; no public page was changed.' >&2
            exit 1
          fi
      - uses: actions/checkout@v4
        with:
          repository: Vance-PIC/Travel_Master_Prices
          ref: main
          path: public-site
          token: ${{ secrets.PUBLIC_PAGES_TOKEN }}
      - run: |
          cp _site/index.html public-site/index.html
          git -C public-site add -- index.html
          if git -C public-site diff --cached --quiet; then exit 0; fi
          git -C public-site -c user.name='github-actions[bot]' -c user.email='41898282+github-actions[bot]@users.noreply.github.com' commit -m 'Update public price dashboard'
          git -C public-site push origin HEAD:main
```
- [ ] **Step 4: 執行全部相關測試、`git diff --check`，並核對 workflow 的觸發事件、權限、單檔發布與憑證處理。**
- [ ] **Step 5: 提交 `ci: publish public price dashboard from monitor snapshots`。**

### Task 4: 發布驗證

**Files:** 無程式變更，除非測試揭露缺陷。

**Interfaces:** GitHub Pages 網址與 Actions 執行結果。

- [ ] **Step 1: 將已驗證分支建立 PR，檢視差異；保持現有監控排程與資料不變。**
- [ ] **Step 2: 取得該次發布核准後，建立只有公開資料的 `Vance-PIC/Travel_Master_Prices`，以 `main` 為預設分支並設 Pages Source 為 Deploy from a branch、`main` / root。由使用者建立限定此 repo Contents read/write 的 fine-grained PAT，存入私人 `Travel_Master` Actions secret `PUBLIC_PAGES_TOKEN`，不讀取權杖值。**
- [ ] **Step 3: 確認已取得當次發布核准，且公開 repo、Pages 與權杖均已就緒，再合併私人 repo PR。合併至 master 可能因 `push` 自動首次發布；檢查該次自動 Actions Run 成功、公開 repo 只更新 `index.html`，並取得 Pages 網址。手動執行只作補跑或再次核對。**
- [ ] **Step 4: 檢查公開頁的價格、幣別、各筆觀測時間、過期／未驗證標示，以及家庭私人資訊未出現；記錄 Run ID、公開網址及未解決問題。此步不執行查價。**

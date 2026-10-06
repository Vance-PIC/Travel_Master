# 公開價格儀表板

公開頁從 master 的本地監控快照產生，GitHub Pages 僅接收 `_site`。任何知道網址的人都能讀取頁面與靜態檔案。

## 公開內容與隱私邊界

頁面依欄位白名單顯示航線、旅行／住宿日期、航空公司、航班號與時間、飯店名稱、已觀測價格與原幣別、來源、觀測時間及驗證／過期狀態。機票最多顯示五筆有效完整去回程組合，按 API 顯示價格排序。除非當次 Booking Options 驗證支持該筆價格，機票標為「API 顯示價格，未驗證為家庭總價」。飯店不自行換匯。

不公開逐日行程、旅客人數與年齡、已訂房狀態或訂房基準、家庭預算、私人備註、監控設定、原始 API 回應與密鑰。不得將完整儀表板或 `travel/nagoya` 目錄作為 Pages artifact。

每筆時間取自該筆觀測，不使用頁面產生時間代替。超過 48 小時的報價標示「資料過期」；缺漏或無效資料顯示相應狀態，不捏造現價。頁面重建只讀取快照，不更動 latest.json 或 history，也不會讓舊報價變新。

## 更新與手動重建

`Publish public price dashboard` workflow 接受：

監控使用 `GITHUB_TOKEN` 推送快照時，不會觸發新的 push workflow，因此以 `workflow_run` 監聽監控完成來更新公開頁。

- master 上 `Nagoya SerpApi flight monitor` 或 `Hotel monitor executor` 完成事件，包括失敗完成。這讓頁面能呈現最後保留快照與原始觀測時間；非 master 的完成事件會略過。
- master 上產生器、公開頁模板或發布 workflow 的變更。
- Actions 頁面的手動 `Run workflow`。

所有執行均檢出 master，執行 `python scripts/build_public_dashboard.py --output _site`，再透過官方 Pages actions 上傳及部署 `_site`。不下載監控 artifact，不新增查價或排程，不讀取查價 secrets。僅授予 contents read、pages write 與 id-token write，並使用 github-pages environment 與專用 concurrency 排隊發布。

本地預覽可在儲存庫根目錄執行上述命令，再開啟 `_site/index.html`。產物不是原始資料備份，請勿將其他檔案複製進 `_site`。

首次正式發布需儲存庫管理者將 Settings → Pages → Source 設為 GitHub Actions，確認 github-pages environment 允許部署，再於 Actions 手動執行。本次程式變更不包含遠端設定或實際發布。發布完成後，從 deployment 的 environment URL 核對價格、每筆資料時間、過期狀態及私人區塊未公開。若發布失敗，查看 Actions 診斷並修正後重跑；前次已發布頁面維持可用。

# 公開價格儀表板

公開頁從私人 `Vance-PIC/Travel_Master` 的 master 監控快照產生，只把脫敏後的 `_site/index.html` 同步到獨立的公開儲存庫 `Vance-PIC/Travel_Master_Prices`（暫定名稱）。該公開儲存庫的 GitHub Pages 從 `main` 分支根目錄發布。任何知道網址的人都能讀取公開儲存庫及頁面。

## 公開內容與隱私邊界

頁面依欄位白名單顯示航線、旅行／住宿日期、航空公司、航班號與時間、飯店名稱、已觀測價格與原幣別、來源、觀測時間及驗證／過期狀態。機票最多顯示五筆有效完整去回程組合，按 API 顯示價格排序。除非當次 Booking Options 驗證支持該筆價格，機票標為「API 顯示價格，未驗證為家庭總價」。飯店不自行換匯。

不公開逐日行程、旅客人數與年齡、已訂房狀態或訂房基準、家庭預算、私人備註、監控設定、原始 API 回應與密鑰。不得將完整儀表板、`travel/nagoya` 目錄、原始快照或整個 `_site` 複製到公開儲存庫。私人 `Travel_Master` 維持私人。

每筆時間取自該筆觀測，不使用頁面產生時間代替。超過 48 小時的報價標示「資料過期」；缺漏或無效資料顯示相應狀態，不捏造現價。頁面重建只讀取快照，不更動 latest.json 或 history，也不會讓舊報價變新。

## 更新與手動重建

監控使用 `GITHUB_TOKEN` 推送快照時，不會觸發新的 push workflow，因此以 `workflow_run` 監聽監控完成來更新公開頁。

`Publish public price dashboard` workflow 接受：

- master 上 `Nagoya SerpApi flight monitor` 或 `Hotel monitor executor` 完成事件，包括失敗完成。這讓頁面能呈現最後保留快照與原始觀測時間；非 master 的完成事件會略過。
- master 上產生器、公開頁模板或發布 workflow 的變更。
- Actions 頁面的手動 `Run workflow`。

所有執行均檢出私人儲存庫 master，執行 `python scripts/build_public_dashboard.py --output _site`，檢查 `PUBLIC_PAGES_TOKEN` 已設定，再檢出公開儲存庫 main。流程只複製 `_site/index.html` 到公開儲存庫根目錄，只暫存這個檔案；內容未變時不提交。不下載監控 artifact，不新增查價或排程，不讀取查價 secrets。私人儲存庫 workflow 的 `GITHUB_TOKEN` 只需 contents read；跨儲存庫提交使用 `PUBLIC_PAGES_TOKEN`，不可把權杖值放在 URL、程式碼或日誌。發布使用專用 concurrency 排隊。

本地預覽可在儲存庫根目錄執行上述命令，再開啟 `_site/index.html`。產物不是原始資料備份，請勿將其他檔案複製進 `_site`。

首次正式發布需先取得該次發布核准，再建立公開 `Vance-PIC/Travel_Master_Prices`，以 `main` 為預設分支，至少有一個初始提交。公開儲存庫只放公開頁所需檔案，不複製私人 repo。於公開儲存庫 Settings → Pages 將 Source 設為「Deploy from a branch」、Branch 設為 `main` / root。由使用者建立僅可存取此公開儲存庫、具 Contents read/write 的 fine-grained GitHub PAT，並在私人 `Travel_Master` 的 Actions secrets 建立 `PUBLIC_PAGES_TOKEN`；不要在對話或文件貼出權杖值。若公開儲存庫名稱在發布前變更，須同步修改 workflow 的 `repository` 設定。

取得當次發布核准，且公開儲存庫與 `PUBLIC_PAGES_TOKEN` 均已就緒後，合併程式至私人儲存庫 master 即可能因 `push` 事件自動首次發布。先檢查這次自動 Actions Run 是否成功、公開儲存庫是否只新增／更新 `index.html`，再核對 Pages 網址上的價格、每筆資料時間、過期狀態與私人區塊未公開。手動執行 `Publish public price dashboard` 僅供補跑或再次核對，不是首次發布的必要觸發。若缺少權杖，流程會明確失敗且不修改公開頁；若發布失敗，前次已發布頁面維持可用。此份程式變更不包含建立公開儲存庫、存放權杖或實際發布。

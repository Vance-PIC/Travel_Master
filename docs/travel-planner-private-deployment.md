# 新版私人部署與 Pages 切換

新版供單一使用者使用，HTML 與 API 同源部署。GitHub Pages 不執行 Python、SQLite 或背景排程；先部署受保護的服務，驗證後才修改 Pages 入口。現有公開報價頁與發布工作流程暫時保留作為回復入口。

## 部署

從專案根目錄建置 `docker build -f Dockerfile.planner -t roam-planner .`。

部署環境必須設定：

- `PLANNER_ACCESS_USERNAME`：私人登入帳號，預設 owner。
- `PLANNER_ACCESS_PASSWORD`：透過主機秘密管理注入的強密碼。
- `PLANNER_REQUIRE_AUTH=true`：缺少密碼時拒絕提供服務。
- `SERPAPI_KEY`、`IGNAV_API_KEY`：沿用供應商環境變數，不放入公開頁面。

服務僅透過 HTTPS 反向代理公開，使用一個 process／一個 worker，避免重複排程。掛載持久儲存到 `/app/flight-tracker/data`，並保存 `/app/flight-tracker/config` 以保留使用者設定。掛載目錄需允許 uid 10001 寫入。健康檢查使用 `/healthz`，此端點只回報存活，不包含私人資料。

P2 預設每 6 小時取得觀測，新鮮度預設 24 小時，可在介面各自調整。服務每 15 分鐘檢查排程；停機期間不查價，恢復後補查到期候選，不補造歷史點。此私人服務的 P2 候選由服務排程負責，GitHub 既有固定航線監控是獨立資料來源，不承接私人候選。

## 資料備份與回復

可從專案根目錄執行 `python scripts/backup_planner.py --database flight-tracker/data/flight_tracker.db --output backups`；使用 SQLite backup 取得一致性副本，並保留設定檔。備份包含私人資料，請放在私人儲存空間。

停服後備份整個 data 與 config 目錄，再升級映像；保留前版映像。回復時停服、恢復備份與前版映像，再啟動。不要將資料庫、金鑰或私人候選推送到 Pages 公開儲存庫。

## 切換前驗收

確認未登入無法讀取頁面或 API；登入後完成 P1 搜尋、P2 累積觀測與目標設定、P3 雙來源通路查價；重啟後草案和價格歷史仍存在；確認手機頁籤、趨勢日期與目標線；確認超過新鮮度補查、排程即使價格新鮮仍會查價。

私人 HTTPS 網址確定後，將現有 Pages 首頁改為前往私人服務的入口，並保留舊報價頁連結。實際切換與遠端發布須在驗收後執行；目前沒有配置主機網址或進行發布。

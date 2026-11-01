# 航班 API 除錯日誌

日誌位於設定資料庫旁的 `logs/api-debug.jsonl`（預設 `flight-tracker/data/logs/`）。每檔約 5 MiB，保留目前檔與 4 份輪替，最多約 25 MiB。記錄 P1 搜尋、P2 即時更新與 P3 通路查價的操作識別碼、來源請求、回應、耗時、HTTP 錯誤類型和驗證結果。平行工作中的個別 API 呼叫另有 call_id 可串起請求與回覆。

金鑰、token、密碼、登入資訊、email／電話欄位與 booking_request 會遮蔽；URL 只保留來源網域。回應會限制長度，超出時標為 truncated。日誌不透過網站提供，也不加入公開 Pages；供個人除錯使用。

重現 P3 問題時，按一次重新查詢通路，再查看該時間附近 stage=P3 的 operation_completed 與相同 query_id 的 provider_response。比對 search_parameters、selected_flights、booking_options 與驗證原因，判斷是否缺少旅客計價證據或解析未涵蓋供應商欄位。未知範圍報價仍不視為已驗證總價。

# L2｜AI 顧問

## 目的

以自然語言協助家族旅行預算與行程方向判斷。

## 路由、狀態與 API

| 項目 | 契約 |
| --- | --- |
| GUI 區塊 | `#tab-ai`，使用 `#chat-log`、`#chat-input` 與快速提問按鈕。 |
| API | `POST /api/ai/chat`，request 為 `{ "message": "...", "conversation_id": "uuid" }`。 |
| DB 對應 | 無直接讀寫；目前 API 不自動把 SQLite 資料注入 prompt。 |
| 外部依賴 | 後端環境變數 `GEMINI_API_KEY` 與 Gemini API。 |
| 回應 | `{ "reply": "...", "conversation_id": "uuid", "degraded": false }`；降級時 `degraded=true`，並帶安全 `code`。 |

送出期間須防止重複送出，成功或降級訊息都附加到本瀏覽器 session 的聊天紀錄；不寫入 SQLite。`message` trim 後必須為 1–2,000 字元，空白回 422；外部服務逾時、限流或失敗皆回安全降級訊息。不可把 API Key、HTTP 原始錯誤內容或機密設定送到前端。

## 畫面與行為

- 提供常用提問與自由輸入訊息。
- 透過後端呼叫 Gemini；前端不得取得或保存 API Key。
- 未設定 Key 或外部服務失敗時，顯示可理解的降級訊息，不讓整個 GUI 失敗；不得宣稱已讀取航班／資料庫資料，除非日後另定義受控 context API。

## 驗收

| ID | 操作 | 預期 |
| --- | --- | --- |
| AI-01 | 送出空白或超長訊息 | 422，保留輸入內容且不呼叫外部服務。 |
| AI-02 | API Key 不存在、逾時或限流 | 以 `degraded=true` 與安全 code 回覆，不洩漏原始例外。 |
| AI-03 | 快速連按送出 | 僅建立一個請求，訊息與回覆順序一致。 |

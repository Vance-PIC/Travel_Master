# API 供應商設定設計

## 目標與已確認需求

使用者希望在 GitHub Pages 選擇航班與飯店使用的 API，依已設定金鑰決定可選選項，並使用 GitHub 帳號登入。金鑰保存在私人儲存庫的 Settings → Secrets and variables → Actions；不使用 workflow_dispatch 的一般文字輸入傳遞金鑰。

航班提供 SerpApi＋Ignav、Ignav only、SerpApi only；飯店提供 SearchApi、SerpApi。設定影響後續定時監控，以及由新設定介面觸發的查詢。儲存設定不啟動付費查詢。既有 MCP 的即時查詢目前直接使用 Cloud Run 的金鑰，第一版保留其明確 engine 語意，不宣稱 GitHub Secrets 可直接供 Cloud Run 使用。

## 現況

- 公開價格頁由私人儲存庫產生，再發布到 Travel_Master_Prices 的 index.html。
- 現有 Cloud Run 容器只提供 Bearer 保護的 /mcp；新增網頁登入與設定 API 不得改變這個端點的驗證。
- flight_search 已有 auto、both、ignav、serpapi；定時 nagoya-flight-monitor.yml 目前只有 SerpApi。
- hotel_executor.py 綁定 SearchApi 的 client、解析及 property resolution，切換必須加入完整 adapter。
- 本機 Python、py 與 .venv 啟動失敗，尚未能執行測試；實作完成前需建立可用的測試執行環境。

## 建議操作流程

1. 公開價格頁增加「API 設定」入口；未登入只能看到登入入口，不顯示私人設定或憑證狀態。
2. 點擊後導向 Cloud Run 上的設定頁並以 GitHub 登入。設定頁由同一後端提供，避免 Pages 與 Cloud Run 跨站 cookie 被瀏覽器封鎖。Pages 是入口，使用者不需手動輸入權杖。
3. 登入後顯示兩組供應商選單、目前設定版本、最近執行所用供應商、金鑰設定狀態與 GitHub Secrets 連結。
4. 缺少金鑰的選項停用並指出原因；「已設定」只代表 secret 存在，不代表金鑰有效或額度充足。403、無法讀取或過期狀態顯示「無法確認」，不誤判未設定。
5. 儲存成功後顯示「下次執行生效」。執行中的工作維持其啟動時讀到的設定版本。

同源設定頁是設計者的建議，尚待使用者核對。第一版不自動替換失敗的供應商，避免超出使用者所選服務與用量。

## 登入與權限

GitHub OAuth authorization-code 流程，使用 state 與 PKCE；client secret 由 Cloud Run secret 注入。登入取得 GitHub 數字 user ID，只允許部署時設定的管理員 ID 清單。GitHub 帳號能登入不等於獲得管理權。

OAuth access token 僅於後端取得身分時使用，不傳入 Pages 或瀏覽器儲存。短效簽章 session 只包含 ID、到期時間及 CSRF 識別；HttpOnly、Secure、SameSite=Lax cookie。變更操作驗證 session、Origin 與 CSRF token，登出清除 session。設定頁不允許被 iframe 嵌入，憑證與 OAuth code 不記錄至應用日誌。

既有 GITHUB_TOKEN 的權限需另外核對；後端只需要私人儲存庫 Contents read/write、Actions read/write 及 Secrets read。金鑰狀態透過 repository secrets metadata 取得，絕不讀取或回傳 secret 值。第一版明確僅支援 repository-level secrets；environment 或 organization secrets 另行支援，避免錯誤宣稱可用。

## 設定與 API 合約

設定以私人儲存庫 config/api-providers.json 為唯一真理，內容只有 schema_version、flight_mode、hotel_provider；不含金鑰。預設保持目前行為：定時航班 serpapi、飯店 searchapi。既有 MCP 即時查詢保留原有 engine 行為；管理型監控與設定頁查詢必須採此設定。

- GET /api/settings：回傳設定、revision（GitHub file SHA）、三種供應商的 configured / missing / unknown 狀態與可選模式。需管理員登入。
- PUT /api/settings：接受 revision、flight_mode（serpapi / ignav / hybrid）、hotel_provider（searchapi / serpapi）；嚴格拒絕額外欄位及未知值。伺服器重新確認需要的 secrets 存在後，以 SHA 更新 Contents API。
- 設定同時被其他人更新時回傳 409；頁面要求重新載入。重送相同設定時回傳既有 revision，不重複提交。
- 錯誤統一為 error.code、error.message；401 未登入、403 無權限、409 版本衝突、422 選項不可用、503 無法確認後端狀態。不將外部 API 的原始例外輸出到網頁。

設定頁的查詢動作僅 dispatch 白名單內的 Actions workflow，回傳 queued 與 run URL；完成後讀取持久化結果，不讓 Cloud Run 直接取得供應商金鑰。既有 MCP 所用 Cloud Run secrets 與 Actions secrets 分別標示，不將兩者狀態混為一談。

設定檔損壞或所選金鑰消失時，監控明確失敗並保留最後有效價格，不自行切換服務。供應商金鑰只注入 Actions 工作：SERPAPI_KEY、SEARCHAPI_KEY、IGNAV_API_KEY；既有 Ignav 別名需在部署說明中列出遷移方式，不將金鑰複製到設定檔。

## 供應商執行規則

航班 hybrid 表示 Ignav 先查，缺少指定航空公司時由 SerpApi 補查；不是每次兩邊全部查詢。Ignav only 不呼叫 SerpApi；SerpApi only 不呼叫 Ignav。新增共同報價格式，保留來源、觀測時間、旅客條件、價格範圍及驗證狀態；Ignav 金額不可直接標成已驗證家庭總價；保留原幣別，禁止沿用即時查詢目前的固定 31.75 匯率換算再當成新台幣報價，缺乏即時匯率證據時不做跨幣別排序或通知。無法實作的特定供應商能力必須顯示限制，不能回退去呼叫被停用的 API。

飯店 adapter 將兩家服務解析成既有 assess() 所需格式，維持指定房型、禁菸、床數、兒童入住、幣別及含稅條件核對。property token 與 resolution 依 provider 分開保存，禁止跨供應商沿用 token。切換不覆寫歷史資料，history 與最新報價保留來源；未取得完整房型條件的最低價只作未驗證觀測，不觸發同房型降價通知。

兩種 API 共用同一 SerpApi key 時，介面明示共用額度。第一版不新增自動購買額度、月用量保證或排程頻率編輯；每次執行保留既有 request budget。不能從 secret 是否存在推斷剩餘額度。

## 驗證與交付條件

- 模擬 GitHub OAuth、Secrets metadata、Contents API，驗證非管理員拒絕、CSRF、session 到期、未知選項、金鑰消失及更新衝突。
- 對五種航班／飯店選項測試實際呼叫路由，停用供應商必須零呼叫；測試缺失金鑰及 provider 專屬 token。
- 既有 tests/ 與 scripts/test_hotel*.py 全數執行；報價投影、隱私白名單與歷史保存無退化。
- 瀏覽器驗證登入入口、可用／停用選項、儲存、衝突與錯誤狀態；mock 測試不消耗查價額度。
- 真實 OAuth、Cloud Run 與 Pages 驗收需部署後執行；付費供應商真實查詢另列用量，未執行不得聲稱已驗證。

交付包含程式、測試、OAuth callback / 管理員 ID / Cloud Run secrets / repository secrets 的設定說明及回滾步驟。部署與推送須依當次發布授權辦理。建立 OAuth app 與部署所需識別值留待實作後的部署設定階段提供，不捏造目前已配置。

## 參考

- https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
- https://docs.github.com/en/rest/actions/secrets
- https://serpapi.com/google-hotels-api
- https://serpapi.com/google-hotels-property-details


## 設計檢查補充

設計檢查指出的 Actions write 與金鑰執行環境差異已納入上述方案：新設定控制 Actions 管理型查詢，既有直接查詢另外標示其 Cloud Run 憑證狀態。現有 hotel_server.py 已有 SearchApi / SerpApi 即時 fallback，但不等同定時監控支援切換；第一版不讓這段舊 fallback 冒充設定已套用。

所有 managed workflow 統一在工作啟動時解析當次 checkout 的設定，記錄其內容 revision 與程式 commit SHA。儲存與排程啟動同時發生時，哪個 revision 已被該 run 讀到便執行哪個版本；頁面展示實際 revision，不保證較早 queued 的工作一定採最新設定。

Ignav 串接檢查需覆蓋呼叫參數名稱（client 使用 departure_date / return_date）、children 條件與回傳幣別；currency 目前未送入 API，不能因請求想用 TWD 就認定回傳是 TWD。這些屬於啟用新路由前的必要驗證。

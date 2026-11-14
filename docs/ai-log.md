# AI 協作與除錯紀錄

## 1. 空間資料庫與 Python 套件的嚴格度差異 (GeoJSON 閉合問題)
* **情境**：在測試 API 邊界條件時，傳入了一個僅有 3 個點（未閉合）的不合法 GeoJSON 多邊形。
* **問題**：系統未如預期回傳 422 錯誤，反而觸發了 500 Internal Server Error。
* **原因分析**：Python 的 `shapely` 套件較寬容，自動閉合了多邊形使得 `is_valid` 檢查通過。但原始 JSON 傳入嚴格遵守規範的 PostGIS 時，觸發了 SQL `DataError`。
* **解法**：在 API 資料庫連線區塊加入 `try...except psycopg.Error`，當資料庫拒絕解析時，優雅地轉換並回傳 422 錯誤提示。

## 2. Docker 環境下的資料庫初始化
* **情境**：初次啟動 Docker Compose 時，發現 PostgreSQL 資料庫內沒有自動建立資料表。
* **原因分析**：原本將 schema 腳本建立在 `db/` 目錄，但官方 PostgreSQL 映像檔只會執行放在 `/docker-entrypoint-initdb.d/` 的腳本。
* **解法**：將檔案移動到正確的掛載路徑 `db/init/01_schema.sql`，並使用 `docker compose down -v` 清除舊的 Volume 後重新啟動，成功建表。

## 3. QGIS 空間查詢工具誤區
* **情境**：嘗試在 QGIS 驗證自動入庫的資料筆數與時間。
* **問題**：將 SQL 語句貼在「數據源管理器」的搜尋列無法執行。
* **解法**：透過 AI 協作釐清，應使用「資料庫管理器 (DB Manager)」的 SQL 視窗來執行包含 `GROUP BY` 的統計語法。
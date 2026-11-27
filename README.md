# sat-planner 衛星觀測日曆

查詢台灣或自訂範圍在未來 14 天內，哪幾天會被 Sentinel-1（雷達）與 Sentinel-2（光學）衛星拍到，並依雲量預報給出觀測建議。

**線上展示**：https://mtingwu.github.io/sat-planner/

> API 部署在 Render 免費方案，閒置後會休眠，第一次載入約需 30–60 秒，頁面上會顯示喚醒提示。

![畫面截圖](docs/screenshot.png)

## 為什麼做這個

颱風或豪雨過後，判釋災情需要衛星影像，但這時天空常被厚雲覆蓋，光學衛星拍不到地面。雷達衛星（SAR）不受雲影響，卻不是每天都會經過同一個地方。

想知道「下一次哪顆衛星、什麼時候會拍到這裡」，原本得自己下載 ESA 的取像計畫檔，一份一份打開比對。這個專案把這件事自動化：每天整理 Sentinel-1（雷達）與 Sentinel-2（光學）的取像計畫，結合雲量預報，告訴使用者未來 14 天哪幾天拍得到，以及在雲量高時該優先使用雷達影像。

## 功能

- **接下來的觀測機會**：直接列出最近幾次拍到查詢範圍的日期、時間、衛星與涵蓋縣市，框選範圍時附上預報雲量。
- **14 天日曆**：每天顯示有過境的衛星。實心標籤代表拍到，空心代表只拍到一部分，虛線代表經過附近但沒涵蓋。
- **條帶地圖**：點選日期，地圖畫出當天所有過境條帶；滑鼠移到明細可單獨標亮某一條。
- **自訂查詢範圍**：框選矩形或多邊形，日曆、建議與覆蓋率都改以該範圍重新計算。
- **觀測建議**：依覆蓋率與雲量判斷當天優先使用光學或雷達，並依預報距今天數標示信心。
- **首次造訪說明**：第一次打開網頁會顯示專案目的與使用方式，之後可從「關於這個網頁」再次開啟。

視覺上以製圖慣例設計：雷達條帶用斜線網紋、光學用實色，日曆標籤與地圖條帶使用同一套語言；底圖為國土測繪中心臺灣通用電子地圖轉灰階，讓條帶成為主角。

## 架構

```mermaid
flowchart LR
    ESA[ESA 取像計畫 KML] --> ingest[ingest_plans<br/>每天]
    OM[Open-Meteo 雲量] --> prefetch[prefetch_weather<br/>每 3 小時]
    NLSC[國土測繪中心<br/>縣市界線 shp] --> build[build_regions.py<br/>一次性]
    subgraph Neon[Neon PostgreSQL + PostGIS]
        acq[(acquisitions<br/>plan_files)]
        wg[(weather_grid)]
        reg[(regions<br/>aoi_presets)]
    end
    ingest --> acq
    prefetch --> wg
    build --> reg
    reg -. 篩選陸地附近格點 .-> prefetch
    acq & wg & reg --> api[FastAPI<br/>Render]
    api -->|JSON| fe[index.html<br/>GitHub Pages]
```

三條資料管線各自寫入資料庫：GitHub Actions 每天入庫取像計畫、每 3 小時預抓雲量；行政區資料由腳本一次性產生。**API 在使用者請求時只讀資料庫，不呼叫任何外部服務**，因此不受第三方 API 的速率限制或停機影響。

| 層 | 技術 |
| --- | --- |
| 後端 | Python 3.12、FastAPI、psycopg 3（連線池）、shapely、httpx |
| 資料庫 | PostgreSQL + PostGIS（正式環境 Neon，本機 Docker） |
| 前端 | 單一 HTML 檔，Leaflet、Leaflet.draw，無建置工具 |
| 排程與 CI | GitHub Actions |
| 部署 | Render（API）、Neon（資料庫）、GitHub Pages（前端） |

## 運作方式

### 各部分使用的技術

| 部分 | 語言 | 主要套件與工具 | 位置 |
| --- | --- | --- | --- |
| 前端網頁 | HTML、CSS、JavaScript | Leaflet（地圖）、Leaflet.draw（框選）、Fetch API、SVG pattern（雷達條帶網紋） | `frontend/index.html` |
| API 伺服器 | Python 3.12 | FastAPI、psycopg 3 連線池、shapely（輸入驗證） | `api/app/main.py`、`api/app/services/` |
| 資料庫 | SQL | PostgreSQL + PostGIS | `db/init/*.sql` |
| 取像計畫入庫 | Python | httpx、BeautifulSoup、shapely | `api/app/jobs/ingest_plans.py` |
| 雲量預抓 | Python | httpx（含重試） | `api/app/jobs/prefetch_weather.py` |
| 行政區前處理 | Python | pyshp、shapely | `scripts/build_regions.py` |
| 排程、測試、部署 | YAML | GitHub Actions | `.github/workflows/` |
| 本機環境 | — | Docker Compose（PostGIS 容器） | `docker-compose.yml` |

前端刻意不使用框架與建置工具，單一 HTML 檔即可部署到 GitHub Pages；所有運算集中在後端與資料庫。

### 串接 ESA 取像計畫

ESA 會在 Sentinel-1 與 Sentinel-2 的「Acquisition Plans」網頁上，以 KML 檔公布各衛星未來約三週的取像計畫。本專案每天由 GitHub Actions 執行一次入庫：

1. **找出最新計畫**（`plans.py`）：下載兩個 ESA 網頁，以 BeautifulSoup 找出所有連結，用正規表示式比對檔名，例如 `s1c_mp_user_20261111t172028_20261203t193600`，從中取出衛星代號與計畫的起訖時間。每顆衛星只取開始時間最晚的一份。最新計畫已經結束的衛星（ESA 尚未發布或已停止發布）不入庫，但會印出紀錄；任一網頁一份計畫都比對不到時直接報錯，避免網頁改版時整組衛星被默默忽略。
2. **下載與去重**：下載 KML 後計算 SHA-256。`plan_files.sha256` 設有唯一限制，同一份檔案不會重複入庫，所以排程重跑是安全的。
3. **解析**（`kml_parser.py`、`normalize.py`）：讀出每個取像的屬性與多邊形，只保留與 118–123°E、21–27°N 相交的取像。接著過濾掉不會產生影像的項目（Sentinel-1 只留 IW、EW、SM 模式；Sentinel-2 只留正常觀測），時間統一轉成 UTC，並依過境的台灣當地時間推算 Sentinel-1 的升降軌。
4. **寫入資料庫**：在同一個交易中記錄計畫檔、刪除新計畫期間內尚未發生的舊取像、寫入新取像。任何一步失敗就整筆 rollback；解析結果為 0 筆時，在交易開始前就報錯，避免舊資料被刪光後又因 SHA-256 已記錄而無法重試。

每顆衛星分開處理，一顆失敗不影響其他衛星；只要有任何失敗，排程就以錯誤結束，在 GitHub Actions 上顯示紅燈。

### PostGIS 在這個專案裡做什麼

所有空間資料都以 `GEOMETRY(MultiPolygon, 4326)`（WGS84 經緯度）存放，取像範圍欄位建有 GIST 空間索引。PostGIS 負責以下幾件事：

**計算覆蓋率**：查詢範圍以 GeoJSON 傳入，用 `ST_GeomFromGeoJSON` 轉成幾何，再與每趟取像的範圍求交集。面積一律轉成 `geography` 在橢球面上計算，得到平方公尺；若直接用經緯度計算，單位會是沒有意義的「平方度」。

```sql
ST_Area(ST_Intersection(a.footprint, aoi.g)::geography)
  / ST_Area(aoi.g::geography) AS coverage
```

**找出涵蓋的縣市**：用 `LATERAL JOIN` 對每趟取像，計算它在查詢範圍內與各縣市的交集面積，依面積排序列出。交集面積不到該趟拍到面積 1% 的縣市不列入，以排除幾何簡化造成的接縫。

**預設查詢範圍**：未框選時以 `aoi_presets` 表中的「台灣」為準。這份幾何由內政部縣市界線產生：先把每個縣市拆成獨立島塊，再依位置分成本島、近岸離島、金馬與遠洋，合併本島與近岸離島後簡化（約 33 萬個頂點降到 3 千個）。之所以不能直接依縣市判斷，是因為行政區劃上高雄市包含東沙與南沙、宜蘭縣包含釣魚臺。

**產生雲量格點**：用 `generate_series` 在支援範圍內每 0.25° 產生一個點，再以 `ST_DWithin` 只保留距離陸地 30 公里內的點，共 152 點，作為雲量預抓的位置。

**輸出給前端**：取像範圍以 `ST_AsGeoJSON` 轉回 GeoJSON，只在使用者點選時才回傳，避免一次傳送大量的長條帶幾何。

為了保護資料庫，每個請求的交易開始時會執行 `SET LOCAL statement_timeout = '8s'`，超時的查詢自動中止。使用 `SET LOCAL` 而非連線參數，是因為 Neon 的連線池（PgBouncer）不支援在連線參數中設定。

### 一次查詢的流程

1. 使用者在地圖上框選範圍，前端同時呼叫 `POST /api/calendar`（日曆狀態）與 `POST /api/opportunities`（雲量與建議）。
2. API 先在 Python 端用 shapely 驗證輸入：必須是單一多邊形、頂點不超過 500 個、完全落在支援範圍內、幾何合法；不符合就回 422 並說明原因。
3. 驗證通過後才查資料庫：檢查面積是否超過 20,000 km²，再一次查出時間窗內的所有取像，連同覆蓋率與涵蓋縣市。
4. `calendar.py` 把結果整理成「日期 × 衛星」的狀態表：覆蓋達門檻為拍到、有交集但不足為部分拍到、在資料庫裡但沒碰到範圍為經過附近、計畫已公布但當天沒有為無過境、超出計畫期間為未公布。
5. `opportunities` 另外從 `weather_grid` 取離範圍中心最近的格點雲量，由 `recommend.py` 判斷每天該優先使用光學或雷達。
6. 所有時間轉成台灣時間（+08:00）後以 JSON 回傳。使用者點選某一天時，前端才呼叫 `GET /api/acquisitions/{id}` 取得條帶範圍並畫在地圖上。

### 雲量預報

雲量來自 Open-Meteo，但**不是在使用者請求時才去抓**。部署初期曾在請求時呼叫，結果因 Render 免費方案的對外 IP 由許多服務共用，被 Open-Meteo 以「每日額度用完」拒絕。現在改由 GitHub Actions 每 3 小時預抓 152 個格點的 14 天逐時雲量存進 `weather_grid`，API 只讀資料庫。抓取失敗時會依序等待 10、30、60 秒重試，最後再補跑一輪；資料超過 12 小時會在網頁上提醒，超過 72 小時則不再使用。

## 設計重點

- **「台灣」的定義**：本島加近岸離島（澎湖、綠島、蘭嶼、小琉球、龜山島等），不含金門、馬祖與遠洋島嶼。縣市界線先依島塊拆開再依位置分類，因為行政區劃上高雄市包含東沙與南沙、宜蘭縣包含釣魚臺，直接以縣市判斷會誤判。
- **覆蓋率門檻**：自訂範圍需覆蓋 50% 以上才算拍到；預設台灣範圍用 10%，因為單一條帶不可能蓋到台灣一半，只掃過一角的取像會標示為部分拍到，並列出涵蓋的縣市。
- **「經過附近」**：入庫時只保留經過 118–123°E、21–27°N 的取像，所以資料庫裡沒有涵蓋查詢範圍的取像，就代表它從附近經過。
- **失敗時說實話**：資料庫連不上回 503、查詢逾時回 503 並說明原因、只有使用者輸入真的有誤才回 422；入庫解析出 0 筆時整筆交易不寫入，避免刪除既有的未來取像。

## API

| 路由 | 說明 |
| --- | --- |
| `POST /api/calendar` | 未來 N 天每顆衛星對查詢範圍的狀態（拍到／部分／經過附近／無過境／未公布）。`geometry` 可省略，省略時以台灣為準。 |
| `POST /api/opportunities` | 自訂範圍的取像清單、雲量與每日觀測建議。 |
| `GET /api/acquisitions/{id}` | 單趟取像的詳細資料與條帶範圍 GeoJSON。 |
| `GET /api/presets/{key}` | 預設查詢範圍的幾何（目前為 `taiwan`）。 |
| `GET /api/status` | 各衛星最新計畫與未來取像數。 |
| `GET /livez` | 程序是否存活，不連資料庫，適合外部監控定時呼叫。 |
| `GET /healthz` | 資料庫狀態與資料新鮮度（各衛星計畫剩餘天數、雲量更新時間）。 |

輸入限制：單一合法多邊形、完全落在支援範圍內、面積不超過 20,000 km²、頂點不超過 500 個；單一查詢超過 8 秒自動中止。所有時間皆以台灣時間（+08:00）輸出。完整格式見部署後的 `/docs`。

## 專案結構

```
api/
  app/
    main.py              API 路由、查詢、輸入驗證、錯誤處理
    config.py            支援的地理範圍
    db.py                連線池
    services/
      calendar.py        把取像整理成「日期 × 衛星」狀態
      recommend.py       每日觀測建議
      weather.py         雲量格點查詢
      plans.py           讀取 ESA 計畫清單
      kml_parser.py      解析 KML 並篩選台灣周邊
      normalize.py       KML 屬性轉成入庫格式
      store.py           寫入取像
    jobs/
      ingest_plans.py    入庫取像計畫（每天）
      prefetch_weather.py 預抓雲量（每 3 小時）
  tests/
db/init/                 建表 SQL，依編號執行
scripts/build_regions.py 由縣市界線 shp 產生 02_regions.sql
frontend/index.html
.github/workflows/       入庫、雲量、測試、部署前端
docs/ai-log.md           AI 協作紀錄
```

## 本機開發

需求：WSL2 或 Linux、Docker、Python 3.12。

```bash
# 資料庫（首次建立 volume 時會執行 db/init/ 的 SQL）
docker compose up -d db
export DATABASE_URL="postgresql://sat:sat@localhost:5432/satplan"

# 已有資料的 volume 需手動匯入新的 SQL，例如
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/init/03_weather_grid.sql

# 後端
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.jobs.ingest_plans        # 抓取衛星計畫
python -m app.jobs.prefetch_weather    # 抓取雲量
uvicorn app.main:app --reload --port 8000

# 前端（另開終端機）
cd frontend && python3 -m http.server 5500
```

打開 http://localhost:5500 。前端在 localhost 時會自動連本機 API。

### 測試

```bash
cd api
pytest -rs
```

單元測試不需要資料庫；整合測試會在資料庫已建表時自動執行，種入假取像後實際呼叫 API。CI 會啟動 PostGIS、匯入 `db/init/*.sql` 後跑完整測試。

## 部署

| 服務 | 設定 |
| --- | --- |
| Render | 環境變數 `DATABASE_URL`；健康檢查路徑設為 `/livez`（用 `/healthz` 會在資料庫短暫異常時被誤判而重啟） |
| Neon | 新增資料表時，先在 Neon 匯入對應的 SQL，再部署程式 |
| GitHub Actions | repository secret 存放資料庫連線字串，供入庫與雲量排程使用 |
| GitHub Pages | 由 `pages.yml` 部署 `frontend/` |

## 已知限制

- **雲量以查詢範圍中心點估計**：取最近的 0.25° 格點，範圍越大誤差越大；雲量只是預報，越遠的日期越不準。
- **Sentinel-1 的升降軌是推算的**：依過境的台灣當地時間判斷（傍晚為升軌、清晨為降軌），並非 KML 提供的欄位。
- **門檻是經驗值**：覆蓋 50%（自訂範圍）與 10%（全台灣）算拍到、雲量 30% 以下算晴朗、預報 3 天內信心高、7 天內中，皆為經驗設定，尚未以實際成像結果驗證。
- **計畫不等於成像**：ESA 可能臨時調整取像計畫，本網站內容僅供規劃參考，並非官方資訊。
- **衛星會隨 ESA 發布狀況增減**：某顆衛星的新計畫延遲發布時，會暫時從日曆消失（例如 S2B 曾延遲數天）；ESA 停止發布的衛星（例如 S1A）不會顯示。
- **僅支援台灣周邊**：查詢範圍必須在 118–123°E、21–27°N 內，因為入庫時只保留這個範圍的取像。
- **排程依賴 GitHub Actions**：免費排程可能延遲或被跳過，因此雲量改為每 3 小時抓取一次並避開整點；公開 repo 若 60 天沒有任何活動，GitHub 會自動停用排程，資料將停止更新。
- **冷啟動**：Render 免費方案閒置後休眠，第一次請求需等待數十秒。

## 後續規劃

- 下拉選單選擇縣市作為查詢範圍（`regions` 表已有縣市資料）
- 將 `main.py` 的查詢與資料模型拆分為獨立模組，並為各端點加上回應模型
- API 改用唯讀資料庫帳號，排程使用寫入帳號
- 加入速率限制與資料庫 migration 機制

## 資料來源與授權

- **取像計畫**：Copernicus Sentinel-1 / Sentinel-2 Acquisition Plans，European Space Agency（ESA）。
- **雲量預報**：[Open-Meteo](https://open-meteo.com/)，資料採 CC BY 4.0 授權；免費 API 限非商業用途。
- **行政區界**：內政部國土測繪中心「直轄市、縣市界線（TWD97 經緯度）」，依政府資料開放授權條款使用。
- **底圖**：內政部國土測繪中心臺灣通用電子地圖；載入失敗時改用 © OpenStreetMap contributors。

各來源的標示與使用條件請以其官方頁面最新說明為準。

## 開發紀錄

本專案在開發過程中與 AI 協作，問題的發現、判斷與修正過程記錄在 [docs/ai-log.md](docs/ai-log.md)。
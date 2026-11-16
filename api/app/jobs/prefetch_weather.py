"""預先抓取台灣周邊格點的雲量預報，存進 weather_grid。

由 GitHub Actions 每 6 小時執行一次：
    python -m app.jobs.prefetch_weather

格點：支援範圍內每 0.25° 一點，只保留距離陸地（本島、近岸離島、金馬）30 km 內的點。
GitHub Actions 連 Open-Meteo 時好時壞，所以每批失敗後會等一段時間再試，
全部跑完後再對仍失敗的批次補跑一輪。
"""
import os
import sys
import time

import httpx
import psycopg
from psycopg.types.json import Jsonb

from app.config import INGEST_BOUNDS
from app.services.weather import fetch_cloud_batch

GRID_STEP = 0.25
NEAR_LAND_M = 30_000
BATCH_SIZE = 50              # 一次請求幾個格點；Open-Meteo 每個格點各算一次額度
BACKOFF_SECONDS = (10, 30, 60)   # 同一批失敗後的等待時間，依序使用
FINAL_PASS_WAIT = 120        # 第一輪結束後，補跑失敗批次前先等一下

GRID_SQL = """
SELECT g.lat, g.lon
FROM (SELECT y AS lat, x AS lon
      FROM generate_series(%(miny)s::numeric, %(maxy)s::numeric, %(step)s::numeric) y,
           generate_series(%(minx)s::numeric, %(maxx)s::numeric, %(step)s::numeric) x) g
WHERE EXISTS (
  SELECT 1 FROM regions r
  WHERE r.zone <> 'remote'
    AND ST_DWithin(r.geom::geography,
                   ST_SetSRID(ST_MakePoint(g.lon::float8, g.lat::float8), 4326)::geography,
                   %(dist)s))
ORDER BY g.lat, g.lon
"""

UPSERT_SQL = """
INSERT INTO weather_grid (lat, lon, hourly) VALUES (%s, %s, %s)
ON CONFLICT (lat, lon) DO UPDATE SET hourly = EXCLUDED.hourly, fetched_at = now()
"""


def grid_points(conn):
    minx, miny, maxx, maxy = INGEST_BOUNDS
    rows = conn.execute(GRID_SQL, {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy,
                                   "step": GRID_STEP, "dist": NEAR_LAND_M}).fetchall()
    return [(float(lat), float(lon)) for lat, lon in rows]


def retryable(e):
    """連線問題、429、5xx 值得再試；其他 4xx（例如參數錯誤）重試也沒用。"""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        return code == 429 or code >= 500
    return isinstance(e, httpx.TransportError)


def fetch_with_retry(batch, label, sleep=time.sleep):
    for attempt, wait in enumerate((*BACKOFF_SECONDS, None), start=1):
        try:
            return fetch_cloud_batch(batch)
        except httpx.HTTPError as e:
            print(f"{label} 第 {attempt} 次失敗：{e!r}", file=sys.stderr)
            if wait is None or not retryable(e):
                return None
            sleep(wait)


def save(conn, batch, results):
    with conn.transaction():
        for (lat, lon), hourly in zip(batch, results):
            conn.execute(UPSERT_SQL, (lat, lon, Jsonb(hourly)))


def run(sleep=time.sleep):
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        points = grid_points(conn)
        batches = [points[i:i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
        print(f"格點數：{len(points)}，共 {len(batches)} 批")

        failed = []
        for n, batch in enumerate(batches, start=1):
            results = fetch_with_retry(batch, f"第 {n} 批", sleep)
            if results is None:
                failed.append((n, batch))      # 保留舊資料，先處理下一批
            else:
                save(conn, batch, results)
            sleep(1)                           # 對免費 API 客氣一點

        if failed:
            print(f"{len(failed)} 批失敗，{FINAL_PASS_WAIT} 秒後補跑一輪")
            sleep(FINAL_PASS_WAIT)
            still = []
            for n, batch in failed:
                results = fetch_with_retry(batch, f"補跑第 {n} 批", sleep)
                if results is None:
                    still.append((n, batch))
                else:
                    save(conn, batch, results)
            failed = still

        bad = sum(len(b) for _, b in failed)
        print(f"完成：成功 {len(points) - bad}，失敗 {bad}")
    if failed:
        sys.exit(1)          # 讓 GitHub Actions 顯示紅燈，方便發現


if __name__ == "__main__":
    run()
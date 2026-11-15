"""預先抓取台灣周邊格點的雲量預報，存進 weather_grid。

由 GitHub Actions 每 6 小時執行一次：
    python -m app.jobs.prefetch_weather

格點：支援範圍內每 0.25° 一點，只保留距離陸地（本島、近岸離島、金馬）30 km 內的點。
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
BATCH_SIZE = 50          # 一次請求幾個格點；Open-Meteo 每個格點各算一次額度

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


def run():
    failed = 0
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        points = grid_points(conn)
        print(f"格點數：{len(points)}")
        for i in range(0, len(points), BATCH_SIZE):
            batch = points[i:i + BATCH_SIZE]
            try:
                results = fetch_cloud_batch(batch)
            except httpx.HTTPError as e:
                # 失敗的批次保留舊資料，不中斷其他批次
                failed += len(batch)
                print(f"第 {i // BATCH_SIZE + 1} 批失敗：{e!r}", file=sys.stderr)
                continue
            with conn.transaction():
                for (lat, lon), hourly in zip(batch, results):
                    conn.execute(UPSERT_SQL, (lat, lon, Jsonb(hourly)))
            time.sleep(1)    # 對免費 API 客氣一點
        print(f"完成：成功 {len(points) - failed}，失敗 {failed}")
    if failed:
        sys.exit(1)          # 讓 GitHub Actions 顯示紅燈，方便發現


if __name__ == "__main__":
    run()
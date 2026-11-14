import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row
from shapely.geometry import shape

from app.db import pool
from app.services.weather import get_cloud, cloud_at
# from app.services.recommend import recommend   # 下一階段才啟用

TPE = ZoneInfo("Asia/Taipei")
MAX_AREA_KM2 = 20000

app = FastAPI(title="Satellite Acquisition Planner")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5500", "https://mtingwu.github.io"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class AOIRequest(BaseModel):
    geometry: dict                       # GeoJSON Polygon
    days: int = Field(10, ge=1, le=14)

AREA_SQL = "SELECT ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography) / 1e6 AS km2"

QUERY = """
WITH aoi AS (
  SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326) AS g
)
SELECT a.platform, a.sensor, a.start_time, a.mode, a.pass_direction,
       ST_Area(ST_Intersection(a.footprint, aoi.g)::geography)
         / ST_Area(aoi.g::geography) AS coverage,
       ST_AsGeoJSON(a.footprint)::json AS footprint
FROM acquisitions a, aoi
WHERE a.start_time BETWEEN now() AND now() + make_interval(days => %(days)s)
  AND ST_Intersects(a.footprint, aoi.g)
ORDER BY a.start_time
"""

STATUS_SQL = """
SELECT DISTINCT ON (p.platform)
       p.platform, p.sensor, p.valid_from, p.valid_to, p.fetched_at,
       (SELECT count(*) FROM acquisitions a
         WHERE a.platform = p.platform AND a.start_time > now()) AS upcoming
FROM plan_files p
WHERE p.valid_to > now()
ORDER BY p.platform, p.valid_from DESC
"""

HORIZON_SQL = """
SELECT sensor, min(valid_to) AS horizon
FROM (SELECT DISTINCT ON (platform) id, sensor, valid_to
      FROM plan_files
      WHERE valid_to > now()
      ORDER BY platform, valid_from DESC) latest
WHERE EXISTS (SELECT 1 FROM acquisitions a WHERE a.plan_file_id = latest.id)
GROUP BY sensor
"""

def plan_horizon(cur):
    """各感測器已公布計畫涵蓋到哪天（台北日期），例如 {'MSI': date, 'SAR': date}。"""
    rows = cur.execute(HORIZON_SQL).fetchall()
    return {r["sensor"]: r["horizon"].astimezone(TPE).date() for r in rows}

@app.get("/api/status")
def status():
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        return {"plans": cur.execute(STATUS_SQL).fetchall()}

@app.post("/api/opportunities")
def opportunities(req: AOIRequest):
    try:
        aoi = shape(req.geometry)
    except Exception:
        raise HTTPException(422, "geometry 不是合法的 GeoJSON")
    if aoi.geom_type != "Polygon" or not aoi.is_valid:
        raise HTTPException(422, "只接受合法的單一多邊形")

    geom = json.dumps(req.geometry)
    warnings = []

    try:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            km2 = cur.execute(AREA_SQL, (geom,)).fetchone()["km2"]
            if km2 > MAX_AREA_KM2:
                raise HTTPException(422, f"範圍 {km2:.0f} km² 超過上限 {MAX_AREA_KM2} km²")
            rows = cur.execute(QUERY, {"geom": geom, "days": req.days}).fetchall()
            horizon = plan_horizon(cur)

            # 優雅降級：雲量取不到時仍回傳取像清單
            center = aoi.centroid
            try:
                hourly = get_cloud(conn, center.y, center.x)
            except httpx.HTTPError:
                hourly = None
                warnings.append("雲量預報暫時無法取得，建議僅依取像時間判斷")
    except psycopg.Error:
        # 當 PostGIS 拒絕不合法的空間資料時，統一回傳 422
        raise HTTPException(422, "資料庫無法解析此 GeoJSON，請確認多邊形座標是否合法（例如起迄點須閉合）")

    for r in rows:
        r["cloud"] = (cloud_at(hourly, r["start_time"])
                      if hourly and r["sensor"] == "MSI" else None)

    return {
        "aoi_km2": round(km2, 1),
        "plan_horizon": horizon,
        "acquisitions": rows,
        # "recommendations": recommend(rows, datetime.now(timezone.utc), req.days, horizon),
        "warnings": warnings,
    }
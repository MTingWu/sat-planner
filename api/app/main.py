import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row
from shapely.geometry import box, shape

from app.config import INGEST_BOUNDS
from app.db import pool
from app.services.weather import get_cloud, cloud_at
from app.services.recommend import recommend, MIN_COVERAGE
from app.services.calendar import build_calendar

import logging
log = logging.getLogger("uvicorn.error")

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

class CalendarRequest(BaseModel):
    geometry: dict | None = None         # 省略時使用預設「台灣」範圍
    days: int = Field(14, ge=1, le=21)

AREA_SQL = "SELECT ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography) / 1e6 AS km2"

QUERY = """
WITH aoi AS (
  SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326) AS g
)
SELECT a.id, a.platform, a.sensor, a.start_time, a.mode, a.pass_direction,
       ST_Area(ST_Intersection(a.footprint, aoi.g)::geography)
         / ST_Area(aoi.g::geography) AS coverage,
       ST_AsGeoJSON(a.footprint)::json AS footprint
FROM acquisitions a, aoi
WHERE a.start_time BETWEEN now() AND now() + make_interval(days => %(days)s)
  AND ST_Intersects(a.footprint, aoi.g)
ORDER BY a.start_time
"""

# 取得各衛星的基本狀態
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
SELECT platform, sensor, valid_to AS horizon
FROM (SELECT DISTINCT ON (platform) id, platform, sensor, valid_to
      FROM plan_files
      WHERE valid_to > now()
      ORDER BY platform, valid_from DESC) latest
WHERE EXISTS (SELECT 1 FROM acquisitions a WHERE a.plan_file_id = latest.id)
"""

# 日曆用：時間窗內「所有」取像（不論是否碰到 AOI），才分得出 near 與 none
# geom 為 NULL 時改用 aoi_presets 的預設台灣範圍
# counties：這趟在查詢範圍內拍到的縣市，依面積大小排序；
# 不到拍到面積 1% 的縣市視為簡化幾何造成的接縫，不列入
CALENDAR_QUERY = """
WITH aoi AS (
  SELECT COALESCE(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s::text), 4326),
                  (SELECT geom FROM aoi_presets WHERE key = 'taiwan')) AS g
),
acq AS (
  SELECT a.id, a.platform, a.sensor, a.start_time, a.pass_direction, aoi.g,
         CASE WHEN ST_Intersects(a.footprint, aoi.g)
              THEN ST_Intersection(a.footprint, aoi.g) END AS inter
  FROM acquisitions a, aoi
  WHERE a.start_time >= %(start)s AND a.start_time < %(end)s
)
SELECT acq.id, acq.platform, acq.sensor, acq.start_time, acq.pass_direction,
       COALESCE(ST_Area(acq.inter::geography) / ST_Area(acq.g::geography), 0) AS coverage,
       COALESCE(c.counties, '{}') AS counties
FROM acq
LEFT JOIN LATERAL (
  SELECT array_agg(county_name ORDER BY m2 DESC) AS counties
  FROM (SELECT r.county_name, sum(ST_Area(ST_Intersection(r.geom, acq.inter)::geography)) AS m2
        FROM regions r
        WHERE acq.inter IS NOT NULL AND ST_Intersects(r.geom, acq.inter)
        GROUP BY r.county_name
        HAVING sum(ST_Area(ST_Intersection(r.geom, acq.inter)::geography))
               >= 0.01 * ST_Area(acq.inter::geography)) t
) c ON true
ORDER BY acq.start_time
"""

PRESET_SQL = "SELECT key, name, ST_AsGeoJSON(geom)::json AS geometry FROM aoi_presets WHERE key = %s"

ACQUISITION_SQL = """
SELECT id, platform, sensor, start_time, end_time, mode, orbit_relative, pass_direction,
       ST_AsGeoJSON(footprint)::json AS footprint
FROM acquisitions WHERE id = %s
"""

SUPPORTED_AREA = box(*INGEST_BOUNDS)

def parse_aoi(geometry):
    """檢查 GeoJSON 並回傳 (shapely 幾何, JSON 字串)。"""
    try:
        aoi = shape(geometry)
    except Exception:
        raise HTTPException(422, "geometry 不是合法的 GeoJSON")
    if aoi.geom_type != "Polygon" or not aoi.is_valid:
        raise HTTPException(422, "只接受合法的單一多邊形")
    if not SUPPORTED_AREA.contains(aoi):
        minx, miny, maxx, maxy = INGEST_BOUNDS
        raise HTTPException(
            422, f"查詢範圍需落在支援區域內（經度 {minx:g}–{maxx:g}°E、緯度 {miny:g}–{maxy:g}°N）")
    return aoi, json.dumps(geometry)

def check_area(cur, geom):
    km2 = cur.execute(AREA_SQL, (geom,)).fetchone()["km2"]
    if km2 > MAX_AREA_KM2:
        raise HTTPException(422, f"範圍 {km2:.0f} km² 超過上限 {MAX_AREA_KM2} km²")
    return km2

def plan_horizon(cur):
    """各衛星已公布計畫涵蓋到哪天（台北日期），例如 {'MSI': {'S2A': date, 'S2B': date}, 'SAR': {'S1C': date}}。"""
    rows = cur.execute(HORIZON_SQL).fetchall()
    horizon = {"MSI": {}, "SAR": {}}
    for r in rows:
        if r["sensor"] in horizon:
            horizon[r["sensor"]][r["platform"]] = r["horizon"].astimezone(TPE).date()
    return horizon

@app.get("/api/status")
def status():
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        plans = cur.execute(STATUS_SQL).fetchall()
    return {"plans": plans}

@app.get("/api/presets/{key}")
def preset(key: str):
    """預設查詢範圍的幾何，前端用來畫出「台灣」指的是哪裡。"""
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(PRESET_SQL, (key,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到這個預設範圍")
    return row

@app.post("/api/calendar")
def calendar(req: CalendarRequest):
    """未來 N 天、每顆衛星對查詢範圍的取像狀態。省略 geometry 時以台灣（本島＋近岸離島）為準。"""
    geom = parse_aoi(req.geometry)[1] if req.geometry is not None else None

    now = datetime.now(timezone.utc)
    today = now.astimezone(TPE).date()
    end = datetime.combine(today + timedelta(days=req.days), time.min, tzinfo=TPE)

    try:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            km2 = check_area(cur, geom) if geom else None
            rows = cur.execute(CALENDAR_QUERY, {"geom": geom, "start": now, "end": end}).fetchall()
            horizon = plan_horizon(cur)
    except psycopg.Error:
        raise HTTPException(422, "資料庫無法解析此 GeoJSON，請確認多邊形座標是否合法（例如起迄點須閉合）")

    # 自訂 AOI 要覆蓋一半才算拍到；整個台灣不可能被單一條帶蓋一半，
    # 改用 10%（約 3,700 km²），只掃到邊角的取像會顯示為 partial
    threshold = MIN_COVERAGE if geom else 0.1
    result = build_calendar(rows, horizon, today, req.days, threshold)
    result["aoi"] = {"source": "custom" if geom else "preset:taiwan",
                     "km2": round(km2, 1) if km2 is not None else None,
                     "hit_threshold": threshold}
    return result

@app.get("/api/acquisitions/{acq_id}")
def acquisition(acq_id: int):
    """單一取像的詳細資料與 footprint，前端點選時才載入。"""
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(ACQUISITION_SQL, (acq_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到這筆取像")
    row["start_time"] = row["start_time"].astimezone(TPE)
    row["end_time"] = row["end_time"].astimezone(TPE)
    return row

@app.post("/api/opportunities")
def opportunities(req: AOIRequest):
    aoi, geom = parse_aoi(req.geometry)
    warnings = []

    try:
        with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            km2 = check_area(cur, geom)
            rows = cur.execute(QUERY, {"geom": geom, "days": req.days}).fetchall()
            horizon = plan_horizon(cur)

            # 優雅降級：雲量取不到時仍回傳取像清單
            center = aoi.centroid
            try:
                hourly = get_cloud(conn, center.y, center.x)
            except httpx.HTTPError as e:
                detail = ""
                if isinstance(e, httpx.HTTPStatusError):
                    detail = f" status={e.response.status_code} body={e.response.text[:300]}"
                log.warning("雲量預報取得失敗：%r%s", e, detail)
                hourly = None
                warnings.append("雲量預報暫時無法取得，建議僅依取像時間判斷")
    except psycopg.Error:
        # 當 PostGIS 拒絕不合法的空間資料時，統一回傳 422
        raise HTTPException(422, "資料庫無法解析此 GeoJSON，請確認多邊形座標是否合法（例如起迄點須閉合）")

    for r in rows:
        r["cloud"] = (cloud_at(hourly, r["start_time"])
                      if hourly and r["sensor"] == "MSI" else None)
        # 保持 tz-aware，FastAPI 會輸出成 "2026-11-20T18:00:00+08:00"
        # 前端不論在哪個時區解析都正確，substring(11, 16) 也仍是台灣時間
        r["start_time"] = r["start_time"].astimezone(TPE)

    return {
        "aoi_km2": round(km2, 1),
        "plan_horizon": horizon,
        "acquisitions": rows,
        "recommendations": recommend(rows, datetime.now(timezone.utc), req.days, horizon),
        "warnings": warnings,
    }
"""用真的 PostGIS 測整個 API：種幾筆假取像，打 API，驗證覆蓋率、狀態、縣市與錯誤處理。
需要已匯入 db/init/*.sql 的資料庫；沒有的話整個檔案略過（CI 會先建表）。"""
import math
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient

TPE = ZoneInfo("Asia/Taipei")
SHA = "pytest-integration"

# 斜切台灣西半部的雷達條帶、東邊外海的光學條帶
WEST_STRIP = "POLYGON((119.8 22.5,121.2 22.5,121.6 25.5,120.2 25.5,119.8 22.5))"
EAST_SEA = "POLYGON((122.4 22,123 22,123 26,122.4 26,122.4 22))"
YUNLIN = {"type": "Polygon", "coordinates": [[[120.2, 23.5], [120.5, 23.5], [120.5, 23.7],
                                              [120.2, 23.7], [120.2, 23.5]]]}


def database_ready():
    try:
        with psycopg.connect(os.environ.get("DATABASE_URL", ""), connect_timeout=3) as c:
            return c.execute("SELECT to_regclass('aoi_presets')").fetchone()[0] is not None
    except psycopg.Error:
        return False


pytestmark = pytest.mark.skipif(not database_ready(), reason="資料庫尚未建表")


@pytest.fixture(scope="module")
def seeded():
    """種一份計畫和兩趟取像（兩天後），測完刪掉。"""
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        c.execute("DELETE FROM plan_files WHERE sha256 LIKE 'pytest-%'")
        plan_id = c.execute(
            """INSERT INTO plan_files (platform, sensor, filename, source_url, valid_from, valid_to, sha256)
               VALUES ('S1Z', 'SAR', 'pytest.kml', 'test', now() - interval '1 day',
                       now() + interval '10 day', %s) RETURNING id""", (SHA,)).fetchone()[0]
        ids = {}
        for key, wkt, offset in (("west", WEST_STRIP, 0), ("east", EAST_SEA, 3600)):
            ids[key] = c.execute(
                """INSERT INTO acquisitions (plan_file_id, platform, sensor, start_time, end_time,
                                            pass_direction, footprint)
                   VALUES (%s, 'S1Z', 'SAR', %s, %s, 'descending',
                           ST_Multi(ST_GeomFromText(%s, 4326))) RETURNING id""",
                (plan_id, start + timedelta(seconds=offset),
                 start + timedelta(seconds=offset + 30), wkt)).fetchone()[0]
        yield {"ids": ids, "date": start.astimezone(TPE).date().isoformat()}
        c.execute("DELETE FROM plan_files WHERE sha256 = %s", (SHA,))   # cascade 刪取像


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:          # with 才會執行 lifespan、開啟連線池
        yield c


def ours(cal, date, acq_id):
    for a in cal["calendar"][date]["S1Z"].get("acquisitions", []):
        if a["id"] == acq_id:
            return a
    raise AssertionError(f"日曆裡找不到取像 {acq_id}")


def test_calendar_taiwan_default(client, seeded):
    cal = client.post("/api/calendar", json={}).json()
    assert cal["aoi"]["source"] == "preset:taiwan"
    west = ours(cal, seeded["date"], seeded["ids"]["west"])
    assert west["coverage"] > 0.1                        # 達預設門檻
    assert "雲林縣" in west["counties"]
    assert west["start_time"].endswith("+08:00")
    assert cal["calendar"][seeded["date"]]["S1Z"]["status"] == "hit"


def test_calendar_custom_aoi(client, seeded):
    cal = client.post("/api/calendar", json={"geometry": YUNLIN}).json()
    west = ours(cal, seeded["date"], seeded["ids"]["west"])
    east = ours(cal, seeded["date"], seeded["ids"]["east"])
    assert west["coverage"] == pytest.approx(1.0, abs=1e-3)
    assert set(west["counties"]) <= {"雲林縣", "嘉義縣", "嘉義市"}
    assert east["coverage"] == 0 and east["counties"] == []   # 經過附近但沒碰到


def test_opportunities_includes_ids(client, seeded):
    r = client.post("/api/opportunities", json={"geometry": YUNLIN, "days": 7})
    assert r.status_code == 200
    assert seeded["ids"]["west"] in {a["id"] for a in r.json()["acquisitions"]}


def test_acquisition_detail_and_preset(client, seeded):
    acq = client.get(f"/api/acquisitions/{seeded['ids']['west']}").json()
    assert acq["footprint"]["type"] == "MultiPolygon"
    assert client.get("/api/acquisitions/999999999").status_code == 404
    assert client.get("/api/presets/taiwan").json()["geometry"]["type"] == "MultiPolygon"


def test_rejects_bad_aoi(client):
    outside = {"type": "Polygon", "coordinates": [[[130, 30], [131, 30], [131, 31], [130, 30]]]}
    assert client.post("/api/calendar", json={"geometry": outside}).status_code == 422
    ring = [[120.5 + 0.1 * math.cos(i / 100), 23.5 + 0.1 * math.sin(i / 100)] for i in range(600)]
    many = {"type": "Polygon", "coordinates": [ring + [ring[0]]]}
    r = client.post("/api/calendar", json={"geometry": many})
    assert r.status_code == 422 and "頂點" in r.json()["detail"]


def test_query_timeout_returns_503(client, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "STATEMENT_TIMEOUT", "1ms")
    r = client.post("/api/calendar", json={})
    assert r.status_code == 503
    assert "過長" in r.json()["detail"]


def test_health_endpoints(client):
    assert client.get("/livez").json() == {"status": "ok"}
    h = client.get("/healthz").json()
    assert h["database"] == "ok" and "S1Z" in h["plans"]["active_days_left"]
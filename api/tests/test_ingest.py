import os
from contextlib import contextmanager

import httpx
import psycopg
import pytest

import app.jobs.ingest_plans as job

PLAN = {"platform": "S1C", "url": "https://example.com/S1C.kml", "filename": "S1C_TEST.kml",
        "start": "20261111T172028", "end": "20261203T193600"}


@contextmanager
def fake_connect(*args, **kwargs):
    yield object()


def test_download_raises_on_http_error(monkeypatch):
    req = httpx.Request("GET", PLAN["url"])
    monkeypatch.setattr(job.httpx, "get", lambda *a, **k: httpx.Response(404, request=req, text="<html>"))
    with pytest.raises(httpx.HTTPStatusError):
        job.download(PLAN["url"])


def test_no_plans_found_exits_with_error(monkeypatch):
    monkeypatch.setattr(job.psycopg, "connect", fake_connect)
    with pytest.raises(SystemExit) as e:
        job.run(get_plans=lambda: {})
    assert e.value.code == 1


def test_one_failure_does_not_stop_others(monkeypatch):
    monkeypatch.setattr(job.psycopg, "connect", fake_connect)
    monkeypatch.setenv("DATABASE_URL", "unused")
    plans = {p: {**PLAN, "platform": p} for p in ("S1C", "S1D", "S2B")}
    done = []

    def ingest(conn, plan):
        if plan["platform"] == "S1D":
            raise job.EmptyPlanError("0 筆")
        done.append(plan["platform"])
        return 3

    with pytest.raises(SystemExit) as e:
        job.run(get_plans=lambda: plans, ingest=ingest)
    assert e.value.code == 1
    assert done == ["S1C", "S2B"]


@pytest.fixture
def db():
    url = os.environ.get("DATABASE_URL", "")
    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.Error:
        pytest.skip("沒有可用的資料庫")
    if conn.execute("SELECT to_regclass('plan_files')").fetchone()[0] is None:
        conn.close()
        pytest.skip("資料庫尚未建表")
    yield conn
    conn.close()


def test_empty_plan_leaves_database_untouched(db, monkeypatch):
    before = db.execute("SELECT (SELECT count(*) FROM plan_files), (SELECT count(*) FROM acquisitions)").fetchone()
    monkeypatch.setattr(job, "parse", lambda content, filename: [])
    with pytest.raises(job.EmptyPlanError):
        job.ingest_one(db, PLAN, fetch=lambda url: b"<kml>changed format</kml>")
    after = db.execute("SELECT (SELECT count(*) FROM plan_files), (SELECT count(*) FROM acquisitions)").fetchone()
    assert after == before
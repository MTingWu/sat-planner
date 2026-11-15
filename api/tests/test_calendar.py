from datetime import date, datetime, timezone

from app.services.calendar import build_calendar

TODAY = date(2026, 11, 15)
HORIZON = {"SAR": {"S1C": date(2026, 12, 5)}, "MSI": {"S2A": date(2026, 11, 16)}}


def acq(id, platform, utc, coverage, sensor="SAR"):
    return {"id": id, "platform": platform, "sensor": sensor,
            "start_time": datetime(*utc, tzinfo=timezone.utc),
            "pass_direction": "ascending", "coverage": coverage}


def status(result, day, platform):
    return result["calendar"][day][platform]["status"]


def test_statuses():
    rows = [
        acq(1, "S1C", (2026, 11, 16, 10, 0), 0.8),
        acq(2, "S1C", (2026, 11, 17, 10, 0), 0.2),
        acq(3, "S1C", (2026, 11, 18, 10, 0), 0.0),
    ]
    r = build_calendar(rows, HORIZON, TODAY, 5, hit_threshold=0.5)
    assert status(r, "2026-11-16", "S1C") == "hit"
    assert status(r, "2026-11-17", "S1C") == "partial"
    assert status(r, "2026-11-18", "S1C") == "near"
    assert status(r, "2026-11-19", "S1C") == "none"
    assert status(r, "2026-11-16", "S2A") == "none"          # 計畫最後一天，已公布
    assert status(r, "2026-11-17", "S2A") == "unpublished"


def test_best_coverage_of_the_day_wins():
    rows = [acq(1, "S1C", (2026, 11, 16, 10, 0), 0.0),
            acq(2, "S1C", (2026, 11, 16, 22, 0), 0.9)]     # 台北時間 11/17 06:00
    r = build_calendar(rows, HORIZON, TODAY, 3, hit_threshold=0.5)
    assert status(r, "2026-11-16", "S1C") == "near"
    assert status(r, "2026-11-17", "S1C") == "hit"


def test_grouped_by_taipei_date():
    rows = [acq(1, "S1C", (2026, 11, 15, 21, 50), 0.6)]     # 台北時間 11/16 05:50
    r = build_calendar(rows, HORIZON, TODAY, 3, hit_threshold=0.5)
    assert status(r, "2026-11-15", "S1C") == "none"
    assert status(r, "2026-11-16", "S1C") == "hit"
    assert r["calendar"]["2026-11-16"]["S1C"]["acquisitions"][0]["start_time"].isoformat() \
        == "2026-11-16T05:50:00+08:00"


def test_preset_threshold_any_intersection_is_hit():
    rows = [acq(1, "S1C", (2026, 11, 16, 10, 0), 0.05)]
    r = build_calendar(rows, HORIZON, TODAY, 3, hit_threshold=0)
    assert status(r, "2026-11-16", "S1C") == "hit"


def test_platform_order_and_dates():
    r = build_calendar([], HORIZON, TODAY, 14, hit_threshold=0.5)
    assert [p["platform"] for p in r["platforms"]] == ["S1C", "S2A"]
    assert r["dates"][0] == "2026-11-15" and len(r["dates"]) == 14


def test_counties_passed_through():
    row = acq(1, "S1C", (2026, 11, 20, 9, 52), 0.015)
    row["counties"] = ["新北市", "宜蘭縣", "基隆市"]
    r = build_calendar([row], HORIZON, TODAY, 7, hit_threshold=0.1)
    cell = r["calendar"]["2026-11-20"]["S1C"]
    assert cell["status"] == "partial"
    assert cell["acquisitions"][0]["counties"] == ["新北市", "宜蘭縣", "基隆市"]
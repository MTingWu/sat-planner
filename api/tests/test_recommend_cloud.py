from datetime import date, datetime, timezone

from app.services.recommend import recommend

NOW = datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)
HORIZON = {"MSI": {"S2B": date(2026, 11, 23)}, "SAR": {"S1D": date(2026, 12, 3)}}


def acq(platform, sensor, cloud):
    return {"platform": platform, "sensor": sensor, "coverage": 1.0, "cloud": cloud,
            "start_time": datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc)}


def day19(rows):
    return next(r for r in recommend(rows, NOW, 7, HORIZON) if r["date"] == "2026-11-19")


def test_unknown_cloud_is_not_called_cloudy():
    r = day19([acq("S1D", "SAR", None), acq("S2B", "MSI", None)])
    assert r["advice"] == "優先雷達 (S1D)"
    assert "雲量偏高" not in r["reason"] and "沒有雲量預報" in r["reason"]


def test_high_cloud_reason_shows_value():
    r = day19([acq("S1D", "SAR", None), acq("S2B", "MSI", 80)])
    assert "80%" in r["reason"] and "偏高" in r["reason"]


def test_clear_sky_prefers_optical():
    r = day19([acq("S1D", "SAR", None), acq("S2B", "MSI", 10)])
    assert r["advice"] == "優先光學 (S2B)"


def test_optical_only_without_forecast():
    r = day19([acq("S2B", "MSI", None)])
    assert r["reason"] == "沒有雲量預報可參考"
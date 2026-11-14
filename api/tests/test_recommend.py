from datetime import date, datetime, timezone
from app.services.recommend import recommend

NOW = datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc)   # 台北 12/1 08:00
KNOWN = {"MSI": date(2026, 12, 10), "SAR": date(2026, 12, 10)}

def acq(sensor, cloud, coverage=1.0):
    return {
        "platform": "S2B" if sensor == "MSI" else "S1D",
        "sensor": sensor,
        "start_time": datetime(2026, 12, 2, 2, 30, tzinfo=timezone.utc),   # 台北 12/2
        "coverage": coverage,
        "cloud": cloud,
    }

def advice_on_dec2(acqs, horizon=KNOWN):
    days = {r["date"]: r for r in recommend(acqs, NOW, 3, horizon)}
    return days["2026-12-02"]["advice"]

def test_clear_sky_prefers_optical():
    assert advice_on_dec2([acq("MSI", 10)]) == "優先光學"

def test_cloudy_falls_back_to_sar():
    assert advice_on_dec2([acq("MSI", 80), acq("SAR", None)]) == "雷達較穩妥"

def test_low_coverage_is_ignored():
    assert advice_on_dec2([acq("MSI", 5, coverage=0.2)]) == "等待下一次觀測"

def test_unpublished_plan_is_not_reported_as_no_acquisition():
    early = {"MSI": date(2026, 12, 1), "SAR": date(2026, 12, 10)}
    assert advice_on_dec2([], horizon=early) == "計畫尚未公布"
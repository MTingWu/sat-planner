from datetime import datetime, timezone, date
from app.services.recommend import recommend

NOW = datetime(2026, 12, 1, tzinfo=timezone.utc)

def acq(sensor, cloud, coverage=1.0):
    platform = "S2B" if sensor == "MSI" else "S1D"
    return {
        "platform": platform,
        "sensor": sensor,
        "start_time": datetime(2026, 12, 2, 10, 30, tzinfo=timezone.utc),
        "coverage": coverage,
        "cloud": cloud,
    }

def advice_on_dec2(acqs, horizon=None):
    if horizon is None:
        # 配合新版巢狀結構
        horizon = {"MSI": {"S2B": date(2026, 12, 10)}, "SAR": {"S1D": date(2026, 12, 10)}}
    days = {r["date"]: r for r in recommend(acqs, NOW, 3, horizon)}
    return days["2026-12-02"]["advice"]

def test_clear_sky_prefers_optical():
    # 預期輸出已改為精確標明衛星名稱
    assert advice_on_dec2([acq("MSI", 10)]) == "優先光學 (S2B)"

def test_cloudy_falls_back_to_sar():
    # "雷達較穩妥" 已升級為 "優先雷達"
    assert advice_on_dec2([acq("MSI", 80), acq("SAR", None)]) == "優先雷達 (S1D)"

def test_low_coverage_is_ignored():
    # "等待下一次觀測" 已升級為明確的 "當日無觀測機會"
    assert advice_on_dec2([acq("MSI", 5, coverage=0.2)]) == "當日無觀測機會"

def test_unpublished_plan_is_not_reported_as_no_acquisition():
    # 設定光學計畫只出到 12/1，雷達出到 12/10
    early = {"MSI": {"S2B": date(2026, 12, 1)}, "SAR": {"S1D": date(2026, 12, 10)}}
    # 預期輸出已升級為 "部分計畫未公布"
    assert advice_on_dec2([], horizon=early) == "部分計畫未公布"
from datetime import datetime, timezone

import pytest

from app.services import plans

NOW = datetime(2026, 11, 26, tzinfo=timezone.utc)
S1_PAGE = """<a href="/documents/d/sentinel/s1c_mp_user_20261111t172028_20261203t193600">S1C</a>
             <a href="/documents/d/sentinel/s1c_mp_user_20261104t172028_20261126t000000">old S1C</a>"""
S2_PAGE = """<a href="https://sentinels.copernicus.eu/documents/d/sentinel/s2b_mp_acq__kml_20261105t120000_20261123t150000">S2B</a>
             <a href="/documents/d/sentinel/s2c_mp_acq__kml_20261119t120000_20261207t150000">S2C</a>"""


def fake_fetch(pages):
    return lambda url: pages["sentinel-1" if "sentinel-1" in url else "sentinel-2"]


def test_latest_per_platform_and_ended_split():
    active, ended = plans.scan_plans(fake_fetch({"sentinel-1": S1_PAGE, "sentinel-2": S2_PAGE}), now=NOW)
    assert set(active) == {"S1C", "S2C"}
    assert active["S1C"]["start"] == "20261111t172028"            # 取開始時間最晚的那份
    assert active["S1C"]["url"].startswith("https://sentinels.copernicus.eu/documents/")
    assert set(ended) == {"S2B"}                                   # 不再默默丟掉


def test_page_without_any_plan_raises():
    with pytest.raises(plans.NoPlansFound):
        plans.scan_plans(fake_fetch({"sentinel-1": S1_PAGE, "sentinel-2": "<html>改版了</html>"}), now=NOW)
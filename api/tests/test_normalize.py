from shapely.geometry import box
from app.services.normalize import normalize

GEOM = box(120, 23, 121, 24)

def test_s2_not_recording_is_dropped():
    attrs = {"style": "NOBS_NOT_RECORDING", "ObservationTimeStart": "2026-11-05T12:07:16.245",
             "ObservationTimeStop": "2026-11-05T12:07:37.893", "OrbitRelative": "123"}
    assert normalize("s2b_mp_acq__kml_20261105t120000_20261123t150000", attrs, GEOM) is None

def test_s2_platform_comes_from_filename():
    attrs = {"style": "NOBS_NOMINAL", "ObservationTimeStart": "2026-11-05T02:07:16.245",
             "ObservationTimeStop": "2026-11-05T02:07:37.893", "OrbitRelative": "123"}
    r = normalize("s2b_mp_acq__kml_20261105t120000_20261123t150000", attrs, GEOM)
    assert r["platform"] == "S2B" and r["pass_direction"] == "descending"

def test_s1_wave_mode_is_dropped():
    attrs = {"SatelliteId": "S1D", "Mode": "WV", "ObservationTimeStart": "2026-11-12T19:11:20",
             "ObservationTimeStop": "2026-11-12T19:18:02", "OrbitRelative": "147"}
    assert normalize("s1d_mp_user_x", attrs, GEOM) is None
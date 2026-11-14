from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TPE = ZoneInfo("Asia/Taipei")
S1_MODES = {"IW", "EW", "SM"}
S2_STYLES = {"NOBS_NOMINAL", "NOBS_NRT", "NOBS_RT"}

def to_utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def normalize(filename, attrs, geom):
    """不會產生可用影像的取像回傳 None。"""
    platform = attrs.get("SatelliteId") or Path(filename).name[:3].upper()
    sensor = "SAR" if platform.startswith("S1") else "MSI"

    if sensor == "SAR" and attrs.get("Mode") not in S1_MODES:
        return None
    if sensor == "MSI" and attrs.get("style") not in S2_STYLES:
        return None

    start = to_utc(attrs["ObservationTimeStart"])
    end = to_utc(attrs["ObservationTimeStop"])

    if sensor == "MSI":
        direction = "descending"
    else:   # S1 晨昏軌道：過台灣時傍晚為升軌、清晨為降軌
        direction = "ascending" if start.astimezone(TPE).hour >= 12 else "descending"

    return {
        "platform": platform, "sensor": sensor,
        "start": start, "end": end,
        "mode": attrs.get("Mode"),
        "orbit_relative": int(attrs["OrbitRelative"]),
        "pass_direction": direction,
        "geom": geom, "attrs": attrs,
    }
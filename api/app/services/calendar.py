"""把取像清單整理成「日期 × 衛星」的日曆狀態。純函式，不碰資料庫，方便測試。"""
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

TPE = ZoneInfo("Asia/Taipei")

# 每一格（某天、某顆衛星）的狀態
#   hit         覆蓋率達門檻
#   partial     有交集但覆蓋率不足
#   near        當天有經過台灣周邊（INGEST_BOUNDS），但沒碰到 AOI
#   none        計畫已公布，當天沒有過境
#   unpublished 計畫尚未公布到這天


def cell_status(acqs, hit_threshold):
    best = max(a["coverage"] for a in acqs)
    if best <= 0:
        return "near"
    return "hit" if best >= hit_threshold else "partial"


def build_calendar(rows, horizon, today, days, hit_threshold):
    """
    rows:      查詢結果，每筆含 id, platform, sensor, start_time, pass_direction, coverage, counties
    horizon:   plan_horizon() 的結果，{"MSI": {"S2B": date, ...}, "SAR": {...}}
    today:     台北日期
    hit_threshold: 覆蓋率達到多少算 hit；預設台灣範圍傳 0（有交集即算）
    """
    platforms = sorted(
        ((p, sensor, until) for sensor, plats in horizon.items() for p, until in plats.items()),
        key=lambda x: (x[1] != "SAR", x[0]),          # SAR 在前，其次依名稱
    )

    by_cell = defaultdict(list)
    for r in rows:
        by_cell[(r["start_time"].astimezone(TPE).date(), r["platform"])].append(r)

    dates = [today + timedelta(days=i) for i in range(days)]
    calendar = {}
    for day in dates:
        cell = {}
        for p, _, until in platforms:
            acqs = by_cell.get((day, p), [])
            if acqs:
                status = cell_status(acqs, hit_threshold)
            elif day > until:
                status = "unpublished"
            else:
                status = "none"

            entry = {"status": status}
            if acqs:
                entry["acquisitions"] = [{
                    "id": a["id"],
                    "start_time": a["start_time"].astimezone(TPE),
                    "pass_direction": a["pass_direction"],
                    "coverage": round(a["coverage"], 3),
                    "counties": list(a.get("counties") or []),
                } for a in acqs]
            cell[p] = entry
        calendar[day.isoformat()] = cell

    return {
        "dates": [d.isoformat() for d in dates],
        "platforms": [{"platform": p, "sensor": s, "published_until": u.isoformat()}
                      for p, s, u in platforms],
        "calendar": calendar,
    }
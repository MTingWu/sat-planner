from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

TPE = ZoneInfo("Asia/Taipei")
MIN_COVERAGE = 0.5   # 取像至少覆蓋範圍的一半
CLEAR_SKY = 30       # 預報雲量低於此值視為光學可用

def confidence(lead_days):
    if lead_days <= 3:
        return "高"
    if lead_days <= 7:
        return "中"
    return "低"

def recommend(acqs, now, days, horizon):
    """horizon：各感測器已公布計畫涵蓋到哪天，例如 {"MSI": date, "SAR": date}。"""
    by_day = defaultdict(list)
    for a in acqs:
        if a["coverage"] >= MIN_COVERAGE:
            by_day[a["start_time"].astimezone(TPE).date()].append(a)

    today = now.astimezone(TPE).date()
    result = []
    for i in range(days + 1):
        day = today + timedelta(days=i)
        items = by_day.get(day, [])
        optical = [a for a in items if a["sensor"] == "MSI"]
        sar = [a for a in items if a["sensor"] == "SAR"]
        optical_known = day <= horizon.get("MSI", today)
        sar_known = day <= horizon.get("SAR", today)
        best = min(optical, key=lambda a: a["cloud"] if a["cloud"] is not None else 101,
                   default=None)

        if best and best["cloud"] is not None and best["cloud"] <= CLEAR_SKY:
            advice = "優先光學"
            reason = f"{best['platform']} 過境時預報雲量 {best['cloud']}%"
        elif sar:
            advice = "雷達較穩妥"
            if optical:
                reason = "光學可能被雲遮蔽"
            elif optical_known:
                reason = "當天沒有光學取像"
            else:
                reason = "光學計畫尚未公布"
        elif best:
            advice = "光學，但雲量偏高"
            reason = (f"預報雲量 {best['cloud']}%" if best["cloud"] is not None
                      else "超出雲量預報範圍")
        elif not (optical_known and sar_known):
            advice = "計畫尚未公布"
            reason = "這天超出部分衛星已公布的觀測計畫"
        else:
            advice = "等待下一次觀測"
            reason = "沒有覆蓋半數以上範圍的取像"

        result.append({
            "date": day.isoformat(),
            "advice": advice,
            "reason": reason,
            "confidence": confidence(i),
        })
    return result
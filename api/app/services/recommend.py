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
        # 1. 取得台灣時間的 datetime 物件
        local_dt = a["start_time"].astimezone(TPE)
        
        # 2. 分群邏輯使用轉換後的台灣日期
        if a["coverage"] >= MIN_COVERAGE:
            by_day[local_dt.date()].append(a)
            
        # 把時間定格在 "2026-11-24T06:00:00"，防止 FastAPI 輸出時亂動時區
        # 迎合前端 index.html 寫的 a.start_time.startsWith(rec.date)
        a["start_time"] = local_dt.strftime("%Y-%m-%dT%H:%M:%S")

    today = now.astimezone(TPE).date()
    result = []
    for i in range(days + 1):
        day = today + timedelta(days=i)
        items = by_day.get(day, [])
        optical = [a for a in items if a["sensor"] == "MSI"]
        sar = [a for a in items if a["sensor"] == "SAR"]
        optical_known = day <= horizon.get("MSI", today)
        sar_known = day <= horizon.get("SAR", today)
        
        best = min(optical, key=lambda a: a["cloud"] if a["cloud"] is not None else 101, default=None)
        best_sar = sar[0] if sar else None

        # 【精細化邏輯】直接把衛星名稱塞進建議裡，並明確區分「無過境」與「未公布」
        if best and best["cloud"] is not None and best["cloud"] <= CLEAR_SKY:
            advice = f"優先光學 ({best['platform']})"
            reason = f"預報雲量 {best['cloud']}%，取像條件佳"
        elif best_sar:
            advice = f"優先雷達 ({best_sar['platform']})"
            if optical:
                reason = f"光學 ({best['platform']}) 雲量偏高，改用雷達不受影響"
            elif optical_known:
                reason = "當天無光學衛星過境"
            else:
                reason = "光學計畫尚未公布"
        elif best:
            advice = f"光學 ({best['platform']})，但需留意雲量"
            reason = f"預報雲量 {best['cloud']}%" if best["cloud"] is not None else "超出雲量預報範圍"
        elif not optical_known and not sar_known:
            advice = "超過計畫預報範圍"
            reason = "官方尚未發布此日期的觀測軌跡"
        else:
            advice = "當日無觀測機會"
            reason = "沒有涵蓋此區域的衛星軌跡"

        result.append({
            "date": day.isoformat(),
            "advice": advice,
            "reason": reason,
            "confidence": confidence(i),
        })
    return result
from datetime import timedelta, timezone

import httpx

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high"
MAX_DISTANCE_DEG = 0.3    # AOI 中心離最近格點超過這個距離，視為沒有資料
MAX_AGE_HOURS = 72        # 超過這個時間的預報不再使用


def fetch_cloud_batch(points):
    """一次抓多個格點的雲量預報。points：[(lat, lon), ...]，回傳與 points 同順序的 hourly 清單。
    只給排程（app.jobs.prefetch_weather）使用，API 請求路徑不呼叫外部服務。"""
    params = {
        "latitude": ",".join(f"{lat:.2f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.2f}" for _, lon in points),
        "hourly": HOURLY_VARS,
        "forecast_days": 14,   # 剛好兩週，不會被加權計次，不要再調高
        "timezone": "UTC",
    }
    # 連線層失敗（逾時、TLS 握手失敗）由 transport 立刻重試；其餘交給呼叫端隔一段時間再試
    transport = httpx.HTTPTransport(retries=2)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(60, connect=15)) as client:
        r = client.get(URL, params=params)
    r.raise_for_status()
    data = r.json()
    data = data if isinstance(data, list) else [data]   # 只有一個點時回傳的是物件
    return [d["hourly"] for d in data]


NEAREST_SQL = """
SELECT hourly, fetched_at,
       sqrt(power(lat::float8 - %(lat)s, 2) + power(lon::float8 - %(lon)s, 2)) AS dist
FROM weather_grid
WHERE fetched_at > now() - make_interval(hours => %(max_age)s)
ORDER BY dist
LIMIT 1
"""


def get_cloud(conn, lat, lon):
    """取離 (lat, lon) 最近格點的預報，回傳 (hourly, fetched_at)；附近沒有可用資料時回傳 (None, None)。"""
    row = conn.execute(NEAREST_SQL, {"lat": lat, "lon": lon, "max_age": MAX_AGE_HOURS}).fetchone()
    if row is None:
        return None, None
    if row["dist"] > MAX_DISTANCE_DEG:
        return None, None
    return row["hourly"], row["fetched_at"]


def cloud_at(hourly, t):
    """取最接近取像時間的整點雲量；超出預報範圍回傳 None。"""
    t = t.astimezone(timezone.utc)
    key = t.replace(minute=0, second=0, microsecond=0)
    if t.minute >= 30:
        key += timedelta(hours=1)
    try:
        i = hourly["time"].index(key.strftime("%Y-%m-%dT%H:%M"))
    except ValueError:
        return None
    return hourly["cloud_cover"][i]
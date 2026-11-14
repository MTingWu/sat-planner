from datetime import timedelta, timezone
import httpx
from psycopg.types.json import Jsonb

URL = "https://api.open-meteo.com/v1/forecast"
TTL_HOURS = 3

def fetch_cloud(lat, lon):
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high",
        "forecast_days": 14,   # 剛好兩週，不會被加權計次，不要再調高
        "timezone": "UTC",
    }
    r = httpx.get(URL, params=params, timeout=10)
    r.raise_for_status()
    return r.json()["hourly"]

def get_cloud(conn, lat, lon):
    lat, lon = round(lat, 1), round(lon, 1)
    row = conn.execute(
        """SELECT hourly FROM weather_cache
           WHERE lat = %s AND lon = %s
             AND fetched_at > now() - make_interval(hours => %s)""",
        (lat, lon, TTL_HOURS),
    ).fetchone()
    if row:
        return row[0]
    hourly = fetch_cloud(lat, lon)
    conn.execute(
        """INSERT INTO weather_cache (lat, lon, hourly) VALUES (%s, %s, %s)
           ON CONFLICT (lat, lon)
           DO UPDATE SET hourly = EXCLUDED.hourly, fetched_at = now()""",
        (lat, lon, Jsonb(hourly)),
    )
    return hourly

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
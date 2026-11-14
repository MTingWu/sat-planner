import re
from datetime import datetime, timezone
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

BASE = "https://sentinels.copernicus.eu"
PAGES = [
    f"{BASE}/copernicus/sentinel-1/acquisition-plans",
    f"{BASE}/copernicus/sentinel-2/acquisition-plans",
]
# 同時符合 s1d_mp_user_... 與 s2b_mp_acq__kml_... 兩種命名
PATTERN = re.compile(r"(s[12][a-z])_mp_.*?(\d{8}t\d{6})_(\d{8}t\d{6})$")

def ts(s):
    """20261112t190903 → UTC datetime"""
    return datetime.strptime(s, "%Y%m%dt%H%M%S").replace(tzinfo=timezone.utc)

def latest_plans():
    latest = {}
    for page in PAGES:
        html = httpx.get(page, timeout=30, follow_redirects=True).text
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            name = a["href"].rstrip("/").split("/")[-1].lower()
            m = PATTERN.search(name)
            if not m:
                continue
            platform, start, end = m.group(1).upper(), m.group(2), m.group(3)
            # 時間戳格式固定，字串比較就等於時間比較
            if platform not in latest or start > latest[platform]["start"]:
                latest[platform] = {
                    "platform": platform, "filename": name,
                    "url": urljoin(BASE, a["href"]),   # 相對與完整網址都能處理
                    "start": start, "end": end,
                }
    now = datetime.now(timezone.utc)
    return {p: v for p, v in latest.items() if ts(v["end"]) > now}
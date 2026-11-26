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


class NoPlansFound(RuntimeError):
    """某個 ESA 頁面一份計畫都比對不到，多半是網頁改版。"""


def ts(s):
    """20261112t190903 → UTC datetime"""
    return datetime.strptime(s, "%Y%m%dt%H%M%S").replace(tzinfo=timezone.utc)


def fetch_page(url):
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text


def parse_page(html):
    """回傳頁面上每顆衛星「開始時間最晚」的那份計畫。"""
    latest = {}
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
    return latest


def scan_plans(fetch=fetch_page, now=None):
    """回傳 (active, ended)：
    active：最新計畫尚未結束的衛星，要入庫
    ended： 最新計畫已經結束的衛星（ESA 尚未發布或已停止發布），只記錄不入庫
    任一頁面比對不到任何計畫就報錯，避免整組衛星被默默忽略。"""
    now = now or datetime.now(timezone.utc)
    latest = {}
    for page in PAGES:
        found = parse_page(fetch(page))
        if not found:
            raise NoPlansFound(f"{page} 找不到任何計畫連結，ESA 網頁可能改版了")
        latest.update(found)
    active = {p: v for p, v in latest.items() if ts(v["end"]) > now}
    ended = {p: v for p, v in latest.items() if ts(v["end"]) <= now}
    return active, ended


def latest_plans():
    """相容舊介面：只回傳要入庫的計畫。"""
    return scan_plans()[0]
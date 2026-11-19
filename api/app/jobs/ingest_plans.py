"""下載各衛星最新的取像計畫 KML 並入庫。由 GitHub Actions 每天執行一次。

失敗模式的保護：
- 下載失敗（404、5xx）直接報錯，不會把錯誤頁面當成 KML 解析
- 一份計畫解析後 0 筆 → 整筆 transaction rollback。否則「刪除舊取像」和「記錄 sha256」
  都會生效，舊資料被刪光，隔天又因為 sha256 相同被略過，空洞會一直留著
- 某顆衛星失敗不影響其他衛星；有任何失敗，最後 exit 1 讓 Actions 亮紅燈
"""
import hashlib
import os
import sys
import tempfile
import traceback

import httpx
import psycopg

from app.services.kml_parser import parse_kml
from app.services.normalize import normalize
from app.services.plans import latest_plans, ts
from app.services.store import save


class EmptyPlanError(RuntimeError):
    """解析後沒有任何可用取像，多半是 ESA 改了 KML 格式。"""


def download(url):
    r = httpx.get(url, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.content


def parse(content, filename):
    with tempfile.NamedTemporaryFile(suffix=".kml") as f:
        f.write(content)
        f.flush()
        # 傳原始檔名，不是暫存檔的亂數名稱
        return [r for a, g in parse_kml(f.name) if (r := normalize(filename, a, g))]


def ingest_one(conn, plan, fetch=download):
    """處理一份計畫。回傳入庫筆數；計畫未更新回傳 None。"""
    content = fetch(plan["url"])
    digest = hashlib.sha256(content).hexdigest()
    sensor = "SAR" if plan["platform"].startswith("S1") else "MSI"
    valid_from, valid_to = ts(plan["start"]), ts(plan["end"])

    # 先在 transaction 外解析：解析失敗或 0 筆時，資料庫完全不動
    records = parse(content, plan["filename"])
    if not records:
        raise EmptyPlanError(f"{plan['filename']} 解析後 0 筆，可能是 ESA 改了 KML 格式")

    with conn.transaction():
        row = conn.execute(
            """INSERT INTO plan_files
                 (platform, sensor, filename, source_url, valid_from, valid_to, sha256)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (sha256) DO NOTHING RETURNING id""",
            (plan["platform"], sensor, plan["filename"], plan["url"],
             valid_from, valid_to, digest),
        ).fetchone()
        if row is None:
            return None

        # 新計畫期間內、尚未發生的舊取像先刪除
        conn.execute(
            """DELETE FROM acquisitions
               WHERE platform = %s
                 AND start_time >= greatest(now(), %s)
                 AND start_time <= %s""",
            (plan["platform"], valid_from, valid_to),
        )
        save(conn, row[0], records)
    return len(records)


def run(get_plans=latest_plans, ingest=ingest_one):
    plans = get_plans()
    if not plans:
        # latest_plans() 是讀 ESA 網頁，網頁改版時會回傳空的，不能當成「沒有更新」
        print("找不到任何計畫，ESA 網頁可能改版了", file=sys.stderr)
        sys.exit(1)

    failed = []
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        for plan in plans.values():
            platform = plan["platform"]
            try:
                n = ingest(conn, plan)
            except Exception:
                failed.append(platform)
                print(f"{platform}: 入庫失敗", file=sys.stderr)
                traceback.print_exc()
                continue
            print(f"{platform}: 計畫未更新，略過" if n is None else f"{platform}: 入庫 {n} 筆")

    if failed:
        print(f"失敗的衛星：{', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
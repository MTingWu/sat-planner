import hashlib, os, tempfile
import httpx, psycopg
from app.services.kml_parser import parse_kml
from app.services.normalize import normalize
from app.services.plans import latest_plans, ts
from app.services.store import save

def run():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        for plan in latest_plans().values():
            content = httpx.get(plan["url"], timeout=60, follow_redirects=True).content
            digest = hashlib.sha256(content).hexdigest()
            sensor = "SAR" if plan["platform"].startswith("S1") else "MSI"
            valid_from, valid_to = ts(plan["start"]), ts(plan["end"])

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
                    print(f"{plan['platform']}: 計畫未更新，略過")
                    continue

                # 新計畫期間內、尚未發生的舊取像先刪除
                conn.execute(
                    """DELETE FROM acquisitions
                       WHERE platform = %s
                         AND start_time >= greatest(now(), %s)
                         AND start_time <= %s""",
                    (plan["platform"], valid_from, valid_to),
                )
                with tempfile.NamedTemporaryFile(suffix=".kml") as f:
                    f.write(content)
                    f.flush()
                    # 傳原始檔名，不是暫存檔的亂數名稱
                    records = [r for a, g in parse_kml(f.name)
                               if (r := normalize(plan["filename"], a, g))]
                save(conn, row[0], records)
                print(f"{plan['platform']}: 入庫 {len(records)} 筆")

if __name__ == "__main__":
    run()
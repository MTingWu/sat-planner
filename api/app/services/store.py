from psycopg.types.json import Jsonb

SQL = """
INSERT INTO acquisitions
  (plan_file_id, platform, sensor, start_time, end_time, mode,
   orbit_relative, pass_direction, footprint, attrs)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, ST_Multi(ST_GeomFromText(%s, 4326)), %s)
ON CONFLICT (platform, start_time) DO UPDATE
  SET plan_file_id = EXCLUDED.plan_file_id,
      end_time = EXCLUDED.end_time,
      footprint = EXCLUDED.footprint,
      attrs = EXCLUDED.attrs
"""

def save(conn, plan_file_id, records):
    rows = [
        (plan_file_id, r["platform"], r["sensor"], r["start"], r["end"], r["mode"],
         r["orbit_relative"], r["pass_direction"], r["geom"].wkt, Jsonb(r["attrs"]))
        for r in records
    ]
    with conn.cursor() as cur:
        cur.executemany(SQL, rows)
"""把內政部「直轄市、縣市界線(TWD97經緯度)」shp 轉成 db/init/02_regions.sql。

只在開發機上執行一次，產出的 SQL 進 repo；API 執行時不需要讀 shp。
    pip install pyshp shapely
    python scripts/build_regions.py

座標系統：TWD97[2020] 經緯度與 WGS84 差距 < 1 m，直接當 EPSG:4326 使用。
"""
from collections import defaultdict
from pathlib import Path

import shapefile
from shapely import wkt
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SHP = ROOT / "data/boundaries/COUNTY_MOI_1140318.shp"
OUT = ROOT / "db/init/02_regions.sql"

SIMPLIFY_DEG = 0.001       # 約 100 m，對數百公里寬的取像條帶已足夠
MIN_PART_DEG2 = 1e-6       # 約 0.01 km²，更小的礁岩直接捨棄

# zone：mainland 本島 / nearshore 近岸離島 / outer 外島 / remote 遠洋
# 遠洋用明確規則列出，方便審查，不靠距離門檻猜
REMOTE_RULES = [
    ("釣魚臺列嶼", lambda c, p: c == "宜蘭縣" and p.x > 123),
    ("北方三島",   lambda c, p: c == "基隆市" and p.y > 25.4),
    ("東沙島",     lambda c, p: c == "高雄市" and p.x < 119 and p.y > 15),
    ("南沙群島",   lambda c, p: c == "高雄市" and p.y < 15),
]
OUTER = {"金門縣": "金門", "連江縣": "馬祖"}
NEARSHORE_NAMES = [   # 只是幫近岸離島取名字，分類本身不依賴它
    ("澎湖群島", lambda c, p: c == "澎湖縣"),
    ("綠島",     lambda c, p: c == "臺東縣" and 22.6 < p.y < 22.7),
    ("蘭嶼",     lambda c, p: c == "臺東縣" and p.y < 22.1),
    ("小琉球",   lambda c, p: c == "屏東縣" and 22.3 < p.y < 22.4 and p.x < 120.4),
    ("龜山島",   lambda c, p: c == "宜蘭縣" and p.x > 121.9),
    ("基隆嶼",   lambda c, p: c == "基隆市" and p.x > 121.75 and p.y < 25.25),
]


def explode(g):
    return list(g.geoms) if hasattr(g, "geoms") else [g]


def as_multi(g):
    polys = [p for p in explode(g) if isinstance(p, Polygon) and not p.is_empty]
    return MultiPolygon(polys)


def load_parts():
    r = shapefile.Reader(str(SHP), encoding="utf-8")
    parts = []
    for rec, s in zip(r.iterRecords(), r.iterShapes()):
        for p in explode(shape(s.__geo_interface__).buffer(0)):
            if p.area >= MIN_PART_DEG2:
                parts.append((rec["COUNTYCODE"], rec["COUNTYNAME"], p))
    return parts


def find_mainland(parts):
    """台灣本陸各縣市拼起來後，面積最大的那塊就是本島輪廓。"""
    candidates = [p for _, name, p in parts if name not in ("金門縣", "連江縣", "澎湖縣")]
    return max(explode(unary_union(candidates)), key=lambda g: g.area)


def classify(name, part, mainland):
    pt = part.representative_point()
    if mainland.contains(pt):
        return "mainland", "本島"
    if name in OUTER:
        return "outer", OUTER[name]
    for island, rule in REMOTE_RULES:
        if rule(name, pt):
            return "remote", island
    for island, rule in NEARSHORE_NAMES:
        if rule(name, pt):
            return "nearshore", island
    return "nearshore", "沿岸小島"


def main():
    parts = load_parts()
    mainland = find_mainland(parts)

    groups = defaultdict(list)          # (code, name, zone, island) -> [polygon]
    taiwan = []                         # 預設範圍：本島 + 近岸離島（用原始幾何合併，避免縣界接縫）
    for code, name, p in parts:
        zone, island = classify(name, p, mainland)
        groups[(code, name, zone, island)].append(p)
        if zone in ("mainland", "nearshore"):
            taiwan.append(p)

    def to_wkt(g):
        g = g.simplify(SIMPLIFY_DEG, preserve_topology=True)
        return wkt.dumps(as_multi(g), rounding_precision=5)

    lines = [
        "-- 由 scripts/build_regions.py 產生，請勿手動修改",
        "-- 資料來源：內政部國土測繪中心「直轄市、縣市界線(TWD97經緯度)」COUNTY_MOI_1140318",
        "BEGIN;",
        "DROP TABLE IF EXISTS regions;",
        "DROP TABLE IF EXISTS aoi_presets;",
        """CREATE TABLE regions (
  id          SERIAL PRIMARY KEY,
  county_code TEXT NOT NULL,
  county_name TEXT NOT NULL,
  zone        TEXT NOT NULL CHECK (zone IN ('mainland','nearshore','outer','remote')),
  island      TEXT NOT NULL,          -- 本島、澎湖群島、綠島、金門、東沙島…
  area_km2    DOUBLE PRECISION,
  geom        GEOMETRY(MultiPolygon, 4326) NOT NULL
);""",
        """CREATE TABLE aoi_presets (
  key   TEXT PRIMARY KEY,             -- 'taiwan'，之後可加 'county:64000' 等
  name  TEXT NOT NULL,
  geom  GEOMETRY(MultiPolygon, 4326) NOT NULL
);""",
    ]
    for (code, name, zone, island), polys in sorted(groups.items()):
        lines.append(
            "INSERT INTO regions (county_code, county_name, zone, island, geom) VALUES "
            f"('{code}', '{name}', '{zone}', '{island}', "
            f"ST_GeomFromText('{to_wkt(unary_union(polys))}', 4326));"
        )
    lines += [
        "INSERT INTO aoi_presets (key, name, geom) VALUES "
        f"('taiwan', '台灣（本島＋近岸離島）', ST_GeomFromText('{to_wkt(unary_union(taiwan))}', 4326));",
        "UPDATE regions SET area_km2 = ST_Area(geom::geography) / 1e6;",
        "CREATE INDEX regions_geom_gix ON regions USING GIST (geom);",
        "CREATE INDEX aoi_presets_geom_gix ON aoi_presets USING GIST (geom);",
        "COMMIT;",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"寫出 {OUT.relative_to(ROOT)}（{OUT.stat().st_size / 1024:.0f} KB）")
    for (code, name, zone, island), polys in sorted(groups.items(), key=lambda kv: (kv[0][2], kv[0][1])):
        n = sum(len(p.exterior.coords) for p in explode(unary_union(polys).simplify(SIMPLIFY_DEG, preserve_topology=True)))
        print(f"  {zone:9s} {name} {island}  {len(polys)} 塊 → {n} 點")


if __name__ == "__main__":
    main()
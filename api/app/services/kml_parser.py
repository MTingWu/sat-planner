from lxml import etree
from shapely.geometry import Polygon, MultiPolygon, box
from app.config import INGEST_BOUNDS

NS = {"kml": "http://www.opengis.net/kml/2.2"}
TAIWAN = box(*INGEST_BOUNDS)

def parse_kml(path):
    tree = etree.parse(path)
    for pm in tree.iterfind(".//kml:Placemark", NS):
        attrs = {
            d.get("name"): (d.findtext("kml:value", namespaces=NS) or "").strip()
            for d in pm.iterfind(".//kml:ExtendedData/kml:Data", NS)
        }
        attrs["style"] = (pm.findtext("kml:styleUrl", namespaces=NS) or "").lstrip("#")

        polys = []
        for ring in pm.iterfind(".//kml:LinearRing", NS):
            if ring.getparent().tag.endswith("innerBoundaryIs"):
                continue
            text = ring.findtext("kml:coordinates", namespaces=NS) or ""
            pts = [tuple(map(float, c.split(",")[:2])) for c in text.split()]
            if len(pts) < 4:
                continue
            if max(p[0] for p in pts) - min(p[0] for p in pts) > 180:
                continue   # 跨換日線的範圍會被誤當成橫跨全球，略過
            polys.append(Polygon(pts))

        if polys:
            geom = MultiPolygon(polys)
            if geom.intersects(TAIWAN):
                yield attrs, geom
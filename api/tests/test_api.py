from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_rejects_point_geometry():
    r = client.post("/api/opportunities",
                    json={"geometry": {"type": "Point", "coordinates": [120.5, 23.7]}, "days": 10})
    assert r.status_code == 422
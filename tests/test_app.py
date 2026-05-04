from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_list_stocks_empty_or_list():
    r = client.get("/api/stocks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_stock_detail_not_found():
    r = client.get("/api/stocks/NOTREAL")
    assert r.status_code == 404

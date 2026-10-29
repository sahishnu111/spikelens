import pytest
from fastapi.testclient import TestClient

from spikelens import main
from spikelens.synthetic import make_series


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


def test_health_and_index(client):
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.get("/")
    assert r.status_code == 200 and "SpikeLens" in r.text


def test_analyze_with_labels(client):
    s = make_series(kind="spikes", seed=7)
    r = client.post("/api/analyze", json={"values": s.values, "timestamps": s.timestamps, "labels": s.labels})
    body = r.json()
    assert r.status_code == 200
    assert body["metrics"]["recall"] > 0.8
    assert body["anomalies"][0]["reason"]
    assert body["detected_period"] == 60


def test_analyze_validation(client):
    assert client.post("/api/analyze", json={"values": [1, 2]}).status_code == 422
    assert client.post("/api/analyze", json={"values": [1, 2, 3], "labels": [True]}).status_code == 422
    assert client.post("/api/analyze", json={"values": [1, 2, 3], "detector": "x"}).status_code == 422


@pytest.mark.parametrize("kind", ["mixed", "logs", "level_shift"])
def test_demo(client, kind):
    d = client.get(f"/api/demo?kind={kind}").json()
    assert len(d["values"]) > 100


def test_upload_csv(client):
    s = make_series(kind="spikes", seed=3, n=500)
    csv = "timestamp,value,label\n" + "\n".join(
        f"{t},{v},{int(lab)}" for t, v, lab in zip(s.timestamps, s.values, s.labels, strict=True))
    r = client.post("/api/upload", files={"file": ("m.csv", csv, "text/csv")}, data={"detector": "ensemble"})
    assert r.status_code == 200, r.text
    assert r.json()["metrics"] is not None


def test_upload_json_and_logs(client):
    r = client.post("/api/upload", files={"file": ("m.json", '{"values":[1,2,3,4,5,50,5,4,3]}', "application/json")})
    assert r.status_code == 200
    logs = client.get("/api/demo/logfile").text
    r = client.post("/api/upload", files={"file": ("access.log", logs, "text/plain")},
                    data={"log_metric": "error_rate"})
    assert r.status_code == 200
    ts = [a["timestamp"] for a in r.json()["anomalies"]]
    assert any("13:3" in t for t in ts)  # error burst at minute 90 => 13:30


def test_upload_bad_file(client):
    r = client.post("/api/upload", files={"file": ("m.csv", "a,b\nx,y\n", "text/csv")})
    assert r.status_code == 422


def test_export(client):
    s = make_series(kind="spikes", seed=7, n=400)
    r = client.post("/api/export?format=csv", json={"values": s.values})
    assert r.text.startswith("index,timestamp,value,score,reason")
    r = client.post("/api/export?format=json", json={"values": s.values})
    assert isinstance(r.json(), list)


def test_stream_lifecycle_and_webhook(client, monkeypatch):
    sent = []

    async def fake(url, name, anomalies):
        sent.append((url, name, anomalies))

    monkeypatch.setattr(main, "_send_webhook", fake)
    created = client.post("/api/streams", json={"name": "lat", "webhook_url": "https://example.com/hook"})
    assert created.status_code == 201
    key, sid = created.json()["api_key"], created.json()["id"]
    pts = [{"value": 10 + (i % 3) * 0.1} for i in range(100)] + [{"value": 99.0}]
    r = client.post("/api/streams/ingest", json={"points": pts}, headers={"x-api-key": key})
    assert r.status_code == 200 and r.json()["anomalies"] == 1
    assert sent and sent[0][0] == "https://example.com/hook"
    got = client.get(f"/api/streams/{sid}", headers={"x-api-key": key}).json()
    assert len(got["values"]) == 101 and len(got["anomalies"]) == 1


def test_stream_auth(client):
    assert client.post("/api/streams/ingest", json={"points": [{"value": 1}]},
                       headers={"x-api-key": "bad"}).status_code == 401
    assert client.post("/api/streams", json={"webhook_url": "ftp://x"}).status_code == 422


def test_metrics_endpoint(client):
    client.get("/api/health")
    text = client.get("/metrics").text
    assert "spikelens_http_requests_total" in text
    assert 'path="/api/health"' in text

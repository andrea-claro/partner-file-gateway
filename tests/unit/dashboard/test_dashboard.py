import random
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.main import create_app, human_bytes
from dashboard.ratelimit import SlidingWindowLimiter
from dashboard.repository import Repository
from dashboard.settings import Settings
from dashboard.simulator import Simulator, list_samples, remote_name_for
from tests.unit.conftest import SAMPLES

NOW = datetime.now(UTC)
HX = {"HX-Request": "true"}


def iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat(timespec="seconds").replace("+00:00", "Z")


class FakeUploader:
    def __init__(self, fail: bool = False) -> None:
        self.uploads: list[tuple[str, bytes]] = []
        self.fail = fail

    def upload(self, remote_name: str, data: bytes) -> None:
        if self.fail:
            raise OSError("connection refused")
        self.uploads.append((remote_name, data))


@pytest.fixture
def tables(dynamodb):
    transfers = dynamodb.create_table(
        TableName="transfers",
        KeySchema=[{"AttributeName": "transfer_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "transfer_id", "AttributeType": "S"},
            {"AttributeName": "partner_id", "AttributeType": "S"},
            {"AttributeName": "received_at", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "by_partner",
                "KeySchema": [
                    {"AttributeName": "partner_id", "KeyType": "HASH"},
                    {"AttributeName": "received_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    partners = dynamodb.create_table(
        TableName="partners",
        KeySchema=[{"AttributeName": "partner_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "partner_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    rows = [
        ("t-delivered", "demo", "orders_basic.csv", "DELIVERED", timedelta(minutes=5)),
        ("t-rejected", "demo", "orders_missing_currency.csv", "REJECTED", timedelta(minutes=3)),
        ("t-failed", "globex", "orders_9.csv", "FAILED", timedelta(minutes=1)),
        ("t-old", "globex", "orders_old.csv", "DELIVERED", timedelta(days=3)),
        ("t-xss", "demo", "<script>alert(1)</script>.csv", "RECEIVED", timedelta(minutes=2)),
    ]
    for transfer_id, partner, filename, status, age in rows:
        transfers.put_item(
            Item={
                "transfer_id": transfer_id,
                "partner_id": partner,
                "filename": filename,
                "status": status,
                "received_at": iso(age),
                "size_bytes": 2048,
                "reason": "schema orders_v1: missing column(s): currency"
                if status == "REJECTED"
                else "",
                "destination_key": f"processed/{partner}/x/{filename}"
                if status == "DELIVERED"
                else "",
                "history": [
                    {"at": iso(age), "status": "RECEIVED", "detail": "Received inbound file"},
                    {"at": iso(age), "status": status, "detail": f"Outcome {status}"},
                ],
            }
        )
    partners.put_item(
        Item={
            "partner_id": "demo",
            "name": "Demo Partner",
            "status": "ACTIVE",
            "allowed_patterns": ["orders_*.csv", "orders_*.json"],
            "max_file_size_bytes": 10485760,
            "schema": "orders_v1",
            "key_fingerprint": "SHA256:abc",
        }
    )
    return dynamodb


def make_client(dynamodb, uploader=None, per_ip=3):
    settings = Settings(samples_dir=SAMPLES, simulate_per_ip_per_minute=per_ip)
    simulator = Simulator(list_samples(SAMPLES), uploader or FakeUploader(), rng=random.Random(1))
    app = create_app(
        settings=settings,
        repository=Repository(dynamodb, "transfers", "partners"),
        simulator=simulator,
    )
    return TestClient(app)


def test_overview_shows_counts_and_latest_transfers(tables):
    response = make_client(tables).get("/")
    assert response.status_code == 200
    html = response.text
    assert "orders_basic.csv" in html
    assert "orders_old.csv" in html  # in the latest 10, but not in the 24 h counts
    assert 'class="card-value">1<' in html.replace("\n", "").replace("  ", "")


def test_security_headers_and_no_api_docs(tables):
    client = make_client(tables)
    response = client.get("/")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_user_content_is_escaped(tables):
    html = make_client(tables).get("/transfers").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_transfers_filters_and_htmx_partial(tables):
    client = make_client(tables)
    html = client.get("/transfers", params={"status": "REJECTED"}).text
    assert "orders_missing_currency.csv" in html
    assert "orders_basic.csv" not in html

    partial = client.get("/transfers", params={"partner": "globex"}, headers=HX).text
    assert "<html" not in partial
    assert partial.index("orders_9.csv") < partial.index("orders_old.csv")  # newest first
    assert "orders_basic.csv" not in partial


def test_unknown_status_filter_is_ignored(tables):
    html = make_client(tables).get("/transfers", params={"status": "<bad>"}).text
    assert "orders_basic.csv" in html


def test_transfer_detail_and_404(tables):
    client = make_client(tables)
    html = client.get("/transfers/t-rejected").text
    assert "missing column(s): currency" in html
    assert "Outcome REJECTED" in html
    assert client.get("/transfers/nope").status_code == 404


def test_partners_page(tables):
    html = make_client(tables).get("/partners").text
    assert "Demo Partner" in html
    assert "orders_*.csv, orders_*.json" in html


def test_healthz(tables):
    assert make_client(tables).get("/healthz").json() == {"status": "ok"}


def test_backend_not_ready_returns_503(dynamodb):
    response = make_client(dynamodb).get("/")
    assert response.status_code == 503
    assert "not reachable yet" in response.text


class TestSimulate:
    def test_uploads_a_sample_as_the_demo_partner(self, tables):
        uploader = FakeUploader()
        response = make_client(tables, uploader).post("/simulate", headers=HX)
        assert response.status_code == 200
        assert "Uploaded" in response.text
        assert len(uploader.uploads) == 1

    def test_requires_the_htmx_header(self, tables):
        uploader = FakeUploader()
        response = make_client(tables, uploader).post("/simulate")
        assert response.status_code == 400
        assert uploader.uploads == []

    def test_is_rate_limited_per_client_ip(self, tables):
        client = make_client(tables, per_ip=2)
        headers = {**HX, "CF-Connecting-IP": "203.0.113.7"}
        assert client.post("/simulate", headers=headers).status_code == 200
        assert client.post("/simulate", headers=headers).status_code == 200
        limited = client.post("/simulate", headers=headers)
        assert limited.status_code == 429
        assert "Rate limit" in limited.text
        other = {**HX, "CF-Connecting-IP": "198.51.100.1"}
        assert client.post("/simulate", headers=other).status_code == 200

    def test_upload_failure_is_reported_without_details(self, tables):
        response = make_client(tables, FakeUploader(fail=True)).post("/simulate", headers=HX)
        assert response.status_code == 502
        assert "connection refused" not in response.text


def test_samples_are_split_by_expected_outcome():
    samples = list_samples(SAMPLES)
    expected = {s.path.name: s.expected for s in samples}
    assert expected["orders_basic.csv"] == "DELIVERED"
    assert expected["orders_broken.json"] == "REJECTED"


@pytest.mark.parametrize("name", ["orders_basic.csv", "orders_batch.json"])
def test_remote_name_keeps_the_partner_pattern(name):
    remote = remote_name_for(Path(name), NOW)
    assert remote != name
    assert fnmatchcase(remote, "orders_*.csv") or fnmatchcase(remote, "orders_*.json")
    assert remote.endswith(Path(name).suffix)


def test_rate_limiter_window():
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 60, clock=lambda: now[0])
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert not limiter.allow("a")
    now[0] = 60.0
    assert limiter.allow("a")


def test_human_bytes():
    assert human_bytes(512) == "512 B"
    assert human_bytes(2048) == "2.0 KB"
    assert human_bytes(None) == "-"

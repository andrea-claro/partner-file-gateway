"""Phase 1 acceptance: SFTP upload -> object in inbound/demo/ -> event on EventBridge."""

import secrets

import pytest

from tests.live import KEYS_DIR, SAMPLES, queue_url, receive_matching, require_stack, sftp_upload

pytestmark = pytest.mark.live


def test_sftp_upload_reaches_eventbridge():
    require_stack()
    sample = SAMPLES / "valid" / "orders_basic.csv"
    name = f"orders_ingest_{secrets.token_hex(3)}.csv"
    sftp_upload("demo", KEYS_DIR / "demo" / "id_ed25519", name, sample.read_bytes())

    event = receive_matching(
        queue_url("pfg-debug-events"),
        lambda body: body.get("detail", {}).get("object", {}).get("key") == f"inbound/demo/{name}",
    )
    assert event["source"] == "aws.s3"
    assert event["detail-type"] == "Object Created"
    assert event["detail"]["bucket"]["name"] == "pfg-transfer"

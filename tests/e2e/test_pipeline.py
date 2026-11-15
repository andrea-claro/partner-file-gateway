"""Phase 2 acceptance: valid files are delivered, invalid ones quarantined, all audited."""

import json
import time

import boto3
import pytest
from botocore.exceptions import ClientError

from tests.live import (
    BUCKET,
    KEYS_DIR,
    SAMPLES,
    queue_url,
    receive_matching,
    require_stack,
    sftp_upload,
    transfers_table,
    unique_name,
    wait_for_transfer,
)

pytestmark = pytest.mark.live

DEMO_KEY = KEYS_DIR / "demo" / "id_ed25519"


def upload_sample(sample):
    require_stack()
    name = unique_name(sample)
    sftp_upload("demo", DEMO_KEY, name, sample.read_bytes())
    return f"inbound/demo/{name}"


def assert_moved(source_key, destination_key, prefix):
    s3 = boto3.client("s3")
    assert destination_key.startswith(prefix)
    s3.head_object(Bucket=BUCKET, Key=destination_key)
    with pytest.raises(ClientError):
        s3.head_object(Bucket=BUCKET, Key=source_key)


@pytest.mark.parametrize("sample", sorted((SAMPLES / "valid").iterdir()), ids=lambda p: p.name)
def test_valid_file_is_delivered(sample):
    source_key = upload_sample(sample)
    item = wait_for_transfer(source_key)

    assert item["status"] == "DELIVERED", item
    assert item["partner_id"] == "demo"
    assert len(item["sha256"]) == 64
    assert [event["status"] for event in item["history"]] == ["RECEIVED", "DELIVERED"]
    assert_moved(source_key, item["destination_key"], "processed/demo/")

    notification = receive_matching(
        queue_url("partner-notifications"),
        lambda body: body.get("transfer_id") == item["transfer_id"],
    )
    assert notification["status"] == "DELIVERED"


@pytest.mark.parametrize("sample", sorted((SAMPLES / "invalid").iterdir()), ids=lambda p: p.name)
def test_invalid_file_is_quarantined(sample):
    source_key = upload_sample(sample)
    item = wait_for_transfer(source_key)

    assert item["status"] == "REJECTED", item
    assert item["reason"]
    assert_moved(source_key, item["destination_key"], "quarantine/demo/")


def test_replayed_event_is_ignored():
    """ADR-004: running the state machine again with the same S3 event is a no-op."""
    source_key = upload_sample(SAMPLES / "valid" / "orders_basic.csv")
    item = wait_for_transfer(source_key)

    sfn = boto3.client("stepfunctions")
    original = sfn.describe_execution(executionArn=item["execution_arn"])
    replay = sfn.start_execution(
        stateMachineArn=original["stateMachineArn"], input=original["input"]
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = sfn.describe_execution(executionArn=replay["executionArn"])["status"]
        if status != "RUNNING":
            break
        time.sleep(2)
    assert status == "SUCCEEDED"

    history = sfn.get_execution_history(executionArn=replay["executionArn"])["events"]
    entered = [
        e["stateEnteredEventDetails"]["name"] for e in history if "stateEnteredEventDetails" in e
    ]
    assert "AlreadyProcessed" in entered
    assert "Route" not in entered

    after = transfers_table().get_item(Key={"transfer_id": item["transfer_id"]})["Item"]
    assert after["status"] == "DELIVERED"
    assert len(after["history"]) == len(item["history"])


def test_execution_input_is_the_s3_event():
    source_key = upload_sample(SAMPLES / "valid" / "orders_batch.json")
    item = wait_for_transfer(source_key)
    execution = boto3.client("stepfunctions").describe_execution(executionArn=item["execution_arn"])
    event = json.loads(execution["input"])
    assert event["detail"]["object"]["key"] == source_key

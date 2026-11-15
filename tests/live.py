"""Helpers for tests that run against the live local stack (make up/infra/bootstrap).

Run them with `make e2e`: inside the tools container, AWS_ENDPOINT_URL points at
LocalStack and the SFTP host key is pinned in .secrets/sftpgo/known_hosts.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import boto3
import paramiko
import pytest
from boto3.dynamodb.conditions import Attr

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = REPO_ROOT / "samples"
BUCKET = os.environ.get("PFG_TRANSFER_BUCKET", "pfg-transfer")
SFTP_HOST = os.environ.get("PFG_SFTP_HOST", "localhost")
SFTP_PORT = int(os.environ.get("PFG_SFTP_PORT", "2022"))
KNOWN_HOSTS = Path(os.environ.get("PFG_KNOWN_HOSTS", REPO_ROOT / ".secrets/sftpgo/known_hosts"))
KEYS_DIR = Path(os.environ.get("PFG_KEYS_DIR", REPO_ROOT / ".secrets/partners"))
FINAL_STATUSES = {"DELIVERED", "REJECTED", "FAILED"}


def require_stack() -> None:
    if not os.environ.get("AWS_ENDPOINT_URL"):
        pytest.fail("AWS_ENDPOINT_URL is not set: run live tests with `make e2e`")
    if not KNOWN_HOSTS.exists():
        pytest.fail(f"{KNOWN_HOSTS} is missing: run `make up` first")


def unique_name(sample: Path) -> str:
    return f"{sample.stem}_e2e{secrets.token_hex(3)}{sample.suffix}"


def sftp_client(username: str, key_path: Path) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_host_keys(str(KNOWN_HOSTS))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        SFTP_HOST,
        port=SFTP_PORT,
        username=username,
        pkey=paramiko.Ed25519Key.from_private_key_file(str(key_path)),
        allow_agent=False,
        look_for_keys=False,
        timeout=15,
    )
    return client


def sftp_upload(username: str, key_path: Path, remote_name: str, data: bytes) -> None:
    client = sftp_client(username, key_path)
    try:
        with client.open_sftp() as sftp:
            sftp.putfo(io.BytesIO(data), remote_name)
    finally:
        client.close()


def transfers_table() -> Any:
    return boto3.resource("dynamodb").Table(os.environ.get("PFG_TRANSFERS_TABLE", "transfers"))


def wait_for_transfer(source_key: str, timeout: float = 180.0) -> dict[str, Any]:
    """Poll the audit trail until the transfer reaches a final status."""
    table = transfers_table()
    deadline = time.monotonic() + timeout
    item: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        items = table.scan(FilterExpression=Attr("source_key").eq(source_key)).get("Items", [])
        if items:
            item = items[0]
            if item.get("status") in FINAL_STATUSES:
                return item
        time.sleep(2)
    pytest.fail(f"no final status for {source_key} after {timeout}s (last: {item})")


def receive_matching(queue_url: str, predicate: Any, timeout: float = 60.0) -> dict[str, Any]:
    sqs = boto3.client("sqs")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=2
        )
        for message in response.get("Messages", []):
            body = json.loads(message["Body"])
            if predicate(body):
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                return body
    pytest.fail(f"no matching message on {queue_url} after {timeout}s")


def queue_url(name: str) -> str:
    return boto3.client("sqs").get_queue_url(QueueName=name)["QueueUrl"]

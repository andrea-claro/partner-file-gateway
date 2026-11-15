"""Shared fixtures for unit tests: moto only, never the network."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "samples"
REGION = "eu-central-2"
BUCKET = "pfg-transfer"


@pytest.fixture(autouse=True)
def _isolated_aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The tools container points AWS_ENDPOINT_URL at LocalStack; unit tests must
    # stay in-process with moto, so drop it and use dummy credentials.
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_REGION", REGION)


@pytest.fixture
def aws() -> Iterator[None]:
    with mock_aws():
        yield


@pytest.fixture
def s3(aws: None) -> Any:
    client = boto3.client("s3", region_name=REGION)
    client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    client.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
    return client


@pytest.fixture
def dynamodb(aws: None) -> Any:
    return boto3.resource("dynamodb", region_name=REGION)


@pytest.fixture
def partners_table(dynamodb: Any) -> Any:
    return dynamodb.create_table(
        TableName="partners",
        KeySchema=[{"AttributeName": "partner_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "partner_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def transfers_table(dynamodb: Any) -> Any:
    return dynamodb.create_table(
        TableName="transfers",
        KeySchema=[{"AttributeName": "transfer_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "transfer_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def s3_event(
    key: str,
    *,
    size: int,
    etag: str = "d41d8cd98f00b204e9800998ecf8427e",
    version_id: str = "",
    time: str = "2026-11-15T21:04:05Z",
    bucket: str = BUCKET,
) -> dict[str, Any]:
    """An EventBridge 'Object Created' event, shaped like the ones S3 emits."""
    obj: dict[str, Any] = {
        "key": key,
        "size": size,
        "etag": etag,
        "sequencer": "0062E99A88DC407460",
    }
    if version_id:
        obj["version-id"] = version_id
    return {
        "version": "0",
        "id": "17793124-05d4-b198-2fde-7ededc63b103",
        "detail-type": "Object Created",
        "source": "aws.s3",
        "account": "000000000000",
        "time": time,
        "region": REGION,
        "resources": [f"arn:aws:s3:::{bucket}"],
        "detail": {
            "version": "0",
            "bucket": {"name": bucket},
            "object": obj,
            "request-id": "N4N7GDK58NMKJ12R",
            "requester": "000000000000",
            "reason": "PutObject",
        },
    }


def active_partner(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "partner_id": "acme",
        "name": "ACME Test Partner",
        "status": "ACTIVE",
        "allowed_patterns": ["orders_*.csv", "orders_*.json"],
        "max_file_size_bytes": 1024 * 1024,
        "schema": "orders_v1",
    }
    item.update(overrides)
    return item

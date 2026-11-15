import pytest
from botocore.exceptions import ClientError

from quarantine.handler import handle as quarantine
from route.handler import handle as route
from tests.unit.conftest import BUCKET


def uploaded(s3, key="inbound/acme/batch/orders_1.csv", body=b"a,b\n1,2\n"):
    version = s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="text/csv")["VersionId"]
    return {
        "transfer_id": "f" * 32,
        "bucket": BUCKET,
        "key": key,
        "version_id": version,
        "partner_id": "acme",
        "filename": key.rsplit("/", 1)[-1],
        "size": len(body),
        "sha256": "abc123",
        "received_at": "2026-11-15T21:04:05Z",
    }


def assert_source_removed(s3, metadata):
    with pytest.raises(ClientError) as exc:
        s3.head_object(Bucket=BUCKET, Key=metadata["key"])
    assert exc.value.response["Error"]["Code"] in ("404", "NoSuchKey")
    # Versioned bucket: the original version is still recoverable.
    s3.head_object(Bucket=BUCKET, Key=metadata["key"], VersionId=metadata["version_id"])


def test_route_moves_file_to_processed(s3):
    metadata = uploaded(s3)
    result = route({"metadata": metadata}, s3=s3)

    destination = "processed/acme/2026/11/15/batch/orders_1.csv"
    assert result["status"] == "DELIVERED"
    assert result["destination_key"] == destination
    assert result["detail"] == f"Delivered to {destination}"

    obj = s3.get_object(Bucket=BUCKET, Key=destination)
    assert obj["Body"].read() == b"a,b\n1,2\n"
    assert obj["ContentType"] == "text/csv"
    assert obj["Metadata"]["pfg-transfer-id"] == metadata["transfer_id"]
    assert obj["Metadata"]["pfg-sha256"] == "abc123"
    assert result["destination_version_id"] == obj["VersionId"]
    assert_source_removed(s3, metadata)


def test_route_copies_the_version_that_was_validated(s3):
    metadata = uploaded(s3, body=b"validated")
    s3.put_object(Bucket=BUCKET, Key=metadata["key"], Body=b"newer upload")
    result = route({"metadata": metadata}, s3=s3)
    body = s3.get_object(Bucket=BUCKET, Key=result["destination_key"])["Body"].read()
    assert body == b"validated"


def test_quarantine_moves_file_with_reason(s3):
    metadata = uploaded(s3)
    reason = "schema orders_v1: Währung fehlt"
    result = quarantine({"metadata": metadata, "reason": reason}, s3=s3)

    destination = "quarantine/acme/2026/11/15/batch/orders_1.csv"
    assert result["status"] == "REJECTED"
    assert result["destination_key"] == destination
    assert result["detail"] == f"Quarantined to {destination}: {reason}"

    obj = s3.head_object(Bucket=BUCKET, Key=destination)
    assert obj["Metadata"]["pfg-quarantine-reason"] == "schema orders_v1: W?hrung fehlt"
    assert_source_removed(s3, metadata)


def test_quarantine_has_a_default_reason(s3):
    result = quarantine({"metadata": uploaded(s3)}, s3=s3)
    assert result["detail"].endswith(": rejected by validation")

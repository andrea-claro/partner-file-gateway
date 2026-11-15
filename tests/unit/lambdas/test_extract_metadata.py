import hashlib

import pytest

from extract_metadata.handler import handle
from extract_metadata.logic import InvalidEventError, parse_event
from pfg_lambda_common.keys import InvalidKeyError
from tests.unit.conftest import BUCKET, s3_event

MAX_HASH = 10 * 1024 * 1024


def upload(s3, key: str, body: bytes, content_type: str = "text/csv"):
    response = s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type)
    return response["VersionId"], response["ETag"].strip('"')


def test_happy_path_returns_metadata(s3):
    body = b"order_id,sku,quantity,unit_price,currency\nA,B,1,1.00,CHF\n"
    version, etag = upload(s3, "inbound/acme/orders_1.csv", body)
    event = s3_event("inbound/acme/orders_1.csv", size=len(body), etag=etag, version_id=version)

    metadata = handle(event, s3=s3, max_hash_bytes=MAX_HASH)

    assert metadata["partner_id"] == "acme"
    assert metadata["filename"] == "orders_1.csv"
    assert metadata["relative_path"] == "orders_1.csv"
    assert metadata["size"] == len(body)
    assert metadata["sha256"] == hashlib.sha256(body).hexdigest()
    assert metadata["version_id"] == version
    assert metadata["content_type"] == "text/csv"
    assert metadata["received_at"] == "2026-11-15T21:04:05Z"
    assert len(metadata["transfer_id"]) == 32


def test_duplicate_event_has_same_transfer_id_but_resend_does_not(s3):
    body = b"same content"
    v1, etag = upload(s3, "inbound/acme/orders_1.csv", body)
    v2, _ = upload(s3, "inbound/acme/orders_1.csv", body)
    first = handle(
        s3_event("inbound/acme/orders_1.csv", size=len(body), etag=etag, version_id=v1),
        s3=s3,
        max_hash_bytes=MAX_HASH,
    )
    duplicate = handle(
        s3_event("inbound/acme/orders_1.csv", size=len(body), etag=etag, version_id=v1),
        s3=s3,
        max_hash_bytes=MAX_HASH,
    )
    resend = handle(
        s3_event("inbound/acme/orders_1.csv", size=len(body), etag=etag, version_id=v2),
        s3=s3,
        max_hash_bytes=MAX_HASH,
    )
    assert first["transfer_id"] == duplicate["transfer_id"]
    assert first["transfer_id"] != resend["transfer_id"]


def test_reads_the_exact_version_from_the_event(s3):
    v1, etag1 = upload(s3, "inbound/acme/orders_1.csv", b"first")
    upload(s3, "inbound/acme/orders_1.csv", b"second, newer")
    metadata = handle(
        s3_event("inbound/acme/orders_1.csv", size=5, etag=etag1, version_id=v1),
        s3=s3,
        max_hash_bytes=MAX_HASH,
    )
    assert metadata["sha256"] == hashlib.sha256(b"first").hexdigest()
    assert metadata["size"] == 5


def test_skips_hash_for_files_above_the_limit(s3):
    body = b"x" * 2048
    version, etag = upload(s3, "inbound/acme/orders_big.csv", body)
    metadata = handle(
        s3_event("inbound/acme/orders_big.csv", size=len(body), etag=etag, version_id=version),
        s3=s3,
        max_hash_bytes=1024,
    )
    assert metadata["sha256"] == ""
    assert metadata["size"] == 2048


def test_invalid_key_fails_before_reading_the_object(s3):
    # No object exists: a GetObject call would raise NoSuchKey instead.
    with pytest.raises(InvalidKeyError):
        handle(s3_event("inbound/orders.csv", size=1), s3=s3, max_hash_bytes=MAX_HASH)


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"detail": {}},
        {**s3_event("inbound/acme/a.csv", size=1), "source": "aws.ec2"},
        {**s3_event("inbound/acme/a.csv", size=1), "detail-type": "Object Deleted"},
        {**s3_event("inbound/acme/a.csv", size=1), "time": "yesterday"},
    ],
)
def test_rejects_events_that_are_not_s3_object_created(event):
    with pytest.raises(InvalidEventError):
        parse_event(event)

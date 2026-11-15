"""Pure logic of ExtractMetadata: parse the S3 event, derive ids, hash the file."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pfg_lambda_common.keys import parse_inbound_key, transfer_id_for


class InvalidEventError(ValueError):
    """The input is not an S3 "Object Created" EventBridge event."""


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    key: str
    size: int
    etag: str
    version_id: str
    sequencer: str
    event_time: datetime


def parse_event(event: dict[str, Any]) -> ObjectRef:
    try:
        detail = event["detail"]
        bucket = detail["bucket"]["name"]
        obj = detail["object"]
        key = obj["key"]
    except (KeyError, TypeError) as exc:
        raise InvalidEventError(f"missing field in S3 event: {exc}") from exc
    if event.get("source") != "aws.s3" or event.get("detail-type") != "Object Created":
        raise InvalidEventError("not an S3 Object Created event")

    raw_time = event.get("time")
    try:
        event_time = datetime.fromisoformat(raw_time) if raw_time else datetime.now(UTC)
    except ValueError as exc:
        raise InvalidEventError(f"invalid event time: {raw_time!r}") from exc
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=UTC)

    return ObjectRef(
        bucket=bucket,
        key=key,
        size=int(obj.get("size") or 0),
        etag=str(obj.get("etag") or "").strip('"'),
        version_id=str(obj.get("version-id") or ""),
        sequencer=str(obj.get("sequencer") or ""),
        event_time=event_time.astimezone(UTC),
    )


def sha256_of(chunks: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def build_metadata(ref: ObjectRef, *, sha256: str, content_type: str) -> dict[str, Any]:
    """The ``$.metadata`` object every later state reads. All values are JSON scalars."""
    inbound = parse_inbound_key(ref.key)
    return {
        "transfer_id": transfer_id_for(
            ref.bucket, ref.key, ref.version_id, ref.etag, ref.sequencer
        ),
        "bucket": ref.bucket,
        "key": ref.key,
        "version_id": ref.version_id,
        "etag": ref.etag,
        "partner_id": inbound.partner_id,
        "relative_path": inbound.relative_path,
        "filename": inbound.filename,
        "size": ref.size,
        "sha256": sha256,
        "content_type": content_type,
        "received_at": ref.event_time.isoformat().replace("+00:00", "Z"),
    }

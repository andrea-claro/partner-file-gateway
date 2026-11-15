"""ExtractMetadata Lambda: identify the partner and fingerprint the uploaded file."""

from __future__ import annotations

import os
from dataclasses import replace
from functools import cache
from typing import Any

import boto3

from extract_metadata.logic import build_metadata, parse_event, sha256_of
from pfg_lambda_common.keys import parse_inbound_key
from pfg_lambda_common.log import JsonLogger

log = JsonLogger("extract_metadata")

CHUNK_SIZE = 1024 * 1024


@cache
def _s3() -> Any:
    return boto3.client("s3")


def handle(event: dict[str, Any], *, s3: Any, max_hash_bytes: int) -> dict[str, Any]:
    ref = parse_event(event)
    parse_inbound_key(ref.key)  # fail fast, before downloading anything

    get_args = {"Bucket": ref.bucket, "Key": ref.key}
    if ref.version_id:
        get_args["VersionId"] = ref.version_id
    response = s3.get_object(**get_args)
    content_type = response.get("ContentType", "application/octet-stream")
    size = int(response.get("ContentLength", ref.size))

    if size > max_hash_bytes:
        # Validate rejects files this large anyway; do not stream them twice.
        response["Body"].close()
        sha256 = ""
    else:
        sha256 = sha256_of(response["Body"].iter_chunks(CHUNK_SIZE))

    metadata = build_metadata(replace(ref, size=size), sha256=sha256, content_type=content_type)
    log.bind(transfer_id=metadata["transfer_id"]).info(
        "metadata extracted",
        partner_id=metadata["partner_id"],
        key=metadata["key"],
        size=metadata["size"],
        sha256=metadata["sha256"],
    )
    return metadata


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    max_hash_bytes = int(os.environ.get("MAX_HASH_BYTES", str(100 * 1024 * 1024)))
    return handle(event, s3=_s3(), max_hash_bytes=max_hash_bytes)

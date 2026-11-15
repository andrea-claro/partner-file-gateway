"""Validate Lambda: partner, file name, size and content schema checks."""

from __future__ import annotations

import os
from functools import cache
from typing import Any

import boto3

from pfg_lambda_common.log import JsonLogger
from validate.logic import Partner, validate_transfer

log = JsonLogger("validate")

DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024


@cache
def _s3() -> Any:
    return boto3.client("s3")


@cache
def _partners_table() -> Any:
    return boto3.resource("dynamodb").Table(os.environ["PARTNERS_TABLE"])


def load_partner(table: Any, partner_id: str) -> Partner | None:
    item = table.get_item(Key={"partner_id": partner_id}, ConsistentRead=True).get("Item")
    return Partner.from_item(item) if item else None


def handle(
    event: dict[str, Any], *, s3: Any, partners_table: Any, default_max_size: int
) -> dict[str, Any]:
    metadata = event["metadata"]
    partner = load_partner(partners_table, metadata["partner_id"])
    limit = (partner.max_file_size_bytes if partner else None) or default_max_size

    def read_content() -> bytes:
        get_args = {"Bucket": metadata["bucket"], "Key": metadata["key"]}
        if metadata.get("version_id"):
            get_args["VersionId"] = metadata["version_id"]
        return s3.get_object(**get_args)["Body"].read(limit + 1)

    result = validate_transfer(metadata, partner, read_content, default_max_size=default_max_size)
    log.bind(transfer_id=metadata["transfer_id"]).info(
        "file accepted" if result.valid else "file rejected",
        partner_id=metadata["partner_id"],
        filename=metadata["filename"],
        valid=result.valid,
        reason=result.reason,
    )
    return result.to_output()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    default_max_size = int(os.environ.get("MAX_FILE_SIZE_BYTES", str(DEFAULT_MAX_FILE_SIZE)))
    return handle(
        event, s3=_s3(), partners_table=_partners_table(), default_max_size=default_max_size
    )

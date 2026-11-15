"""Route Lambda: move an accepted file to processed/<partner>/<yyyy>/<mm>/<dd>/."""

from __future__ import annotations

from datetime import datetime
from functools import cache
from typing import Any

import boto3

from pfg_lambda_common.keys import PROCESSED_PREFIX, destination_key, parse_inbound_key
from pfg_lambda_common.log import JsonLogger
from pfg_lambda_common.s3move import move_object

log = JsonLogger("route")

STATUS = "DELIVERED"


@cache
def _s3() -> Any:
    return boto3.client("s3")


def handle(event: dict[str, Any], *, s3: Any) -> dict[str, Any]:
    metadata = event["metadata"]
    inbound = parse_inbound_key(metadata["key"])
    destination = destination_key(
        PROCESSED_PREFIX, inbound, datetime.fromisoformat(metadata["received_at"])
    )
    version_id = move_object(
        s3,
        bucket=metadata["bucket"],
        source_key=metadata["key"],
        source_version_id=metadata.get("version_id", ""),
        destination_key=destination,
        metadata={
            "pfg-transfer-id": metadata["transfer_id"],
            "pfg-partner-id": metadata["partner_id"],
            "pfg-sha256": metadata["sha256"],
        },
    )
    log.bind(transfer_id=metadata["transfer_id"]).info(
        "file delivered", partner_id=metadata["partner_id"], destination_key=destination
    )
    return {
        "status": STATUS,
        "destination_key": destination,
        "destination_version_id": version_id,
        "detail": f"Delivered to {destination}",
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return handle(event, s3=_s3())

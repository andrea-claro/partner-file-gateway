"""Read-only access to the partners and transfers tables.

The demo holds at most a few thousand transfers, so a bounded Scan is simpler
than maintaining extra indexes. The by_partner GSI is used for partner filters.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

STATUSES = ("RECEIVED", "DELIVERED", "REJECTED", "FAILED")


def _plain(value: Any) -> Any:
    """DynamoDB numbers arrive as Decimal; templates want int/float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


class Repository:
    def __init__(
        self, dynamodb: Any, transfers_table: str, partners_table: str, scan_limit: int = 5000
    ) -> None:
        self.transfers_table = dynamodb.Table(transfers_table)
        self.partners_table = dynamodb.Table(partners_table)
        self.scan_limit = scan_limit

    def _scan(self, table: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {}
        while len(items) < self.scan_limit:
            page = table.scan(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [_plain(item) for item in items[: self.scan_limit]]

    def transfers(
        self, *, status: str | None = None, partner: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if partner:
            page = self.transfers_table.query(
                IndexName="by_partner",
                KeyConditionExpression=Key("partner_id").eq(partner),
                ScanIndexForward=False,
                Limit=self.scan_limit,
            )
            items = [_plain(item) for item in page.get("Items", [])]
        else:
            items = self._scan(self.transfers_table)
        if status:
            items = [item for item in items if item.get("status") == status]
        items.sort(key=lambda item: item.get("received_at", ""), reverse=True)
        return items[:limit]

    def transfer(self, transfer_id: str) -> dict[str, Any] | None:
        item = self.transfers_table.get_item(Key={"transfer_id": transfer_id}).get("Item")
        return _plain(item) if item else None

    def partners(self) -> list[dict[str, Any]]:
        return sorted(self._scan(self.partners_table), key=lambda item: item["partner_id"])

    def summary(self, now: datetime) -> dict[str, Any]:
        since = (now - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
        items = self._scan(self.transfers_table)
        recent = Counter(
            item.get("status") for item in items if item.get("received_at", "") >= since
        )
        return {
            "last_24h": {status: recent.get(status, 0) for status in STATUSES},
            "total": len(items),
        }

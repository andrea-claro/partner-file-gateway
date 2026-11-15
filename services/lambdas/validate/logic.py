"""Pure logic of Validate: decide whether a transfer is accepted or quarantined."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from validate.schemas import summarize, validate_content

STATUS_ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class Partner:
    partner_id: str
    status: str
    allowed_patterns: tuple[str, ...]
    max_file_size_bytes: int | None = None
    schema: str | None = None

    @classmethod
    def from_item(cls, item: Mapping[str, Any]) -> Partner:
        max_size = item.get("max_file_size_bytes")
        return cls(
            partner_id=str(item["partner_id"]),
            status=str(item.get("status", "")),
            allowed_patterns=tuple(str(p) for p in item.get("allowed_patterns") or ()),
            max_file_size_bytes=int(max_size) if max_size is not None else None,
            schema=str(item["schema"]) if item.get("schema") else None,
        )


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str = ""

    def to_output(self) -> dict[str, Any]:
        # reason is always a string: the state machine writes it to DynamoDB.
        return {"valid": self.valid, "reason": self.reason}


def _reject(reason: str) -> ValidationResult:
    return ValidationResult(valid=False, reason=reason)


def validate_transfer(
    metadata: Mapping[str, Any],
    partner: Partner | None,
    read_content: Callable[[], bytes],
    *,
    default_max_size: int,
) -> ValidationResult:
    """Checks run cheapest first; the file body is only read for the schema check."""
    partner_id = metadata["partner_id"]
    if partner is None:
        return _reject(f"unknown partner '{partner_id}'")
    if partner.status != STATUS_ACTIVE:
        return _reject(f"partner '{partner_id}' is {partner.status.lower() or 'not active'}")

    filename = metadata["filename"]
    if not any(fnmatchcase(filename, pattern) for pattern in partner.allowed_patterns):
        allowed = ", ".join(partner.allowed_patterns) or "none"
        return _reject(f"file name '{filename}' does not match the allowed patterns ({allowed})")

    size = int(metadata["size"])
    if size == 0:
        return _reject("file is empty")
    max_size = partner.max_file_size_bytes or default_max_size
    if size > max_size:
        return _reject(f"file is {size} bytes, the limit is {max_size} bytes")

    if partner.schema:
        errors = validate_content(partner.schema, filename, read_content())
        if errors:
            return _reject(f"schema {partner.schema}: {summarize(errors)}")

    return ValidationResult(valid=True)

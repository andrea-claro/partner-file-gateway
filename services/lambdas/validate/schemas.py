"""Content schemas a partner can be bound to (``partners.schema``).

Only one schema exists today, ``orders_v1``: purchase orders sent as CSV (with a
header row) or as a JSON array of objects. Adding a schema means adding a
``Schema`` instance to ``SCHEMAS``.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_REPORTED_ERRORS = 5

FieldCheck = Callable[[Any], str | None]


def _text(max_length: int) -> FieldCheck:
    def check(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return "must be a non-empty string"
        if len(value) > max_length:
            return f"must be at most {max_length} characters"
        return None

    return check


def _positive_int(value: Any) -> str | None:
    if isinstance(value, bool):
        return "must be a positive integer"
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        number = int(value)
    else:
        return "must be a positive integer"
    return None if number >= 1 else "must be a positive integer"


def _money(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return "must be a non-negative amount with at most 2 decimals"
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return "must be a non-negative amount with at most 2 decimals"
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        return "must be a non-negative amount with at most 2 decimals"
    return None


def _currency(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value):
        return None
    return "must be a 3-letter ISO 4217 code such as CHF"


@dataclass(frozen=True)
class Schema:
    name: str
    fields: Mapping[str, FieldCheck]

    def check_record(self, record: Mapping[str, Any]) -> list[str]:
        missing = [name for name in self.fields if name not in record]
        if missing:
            return [f"missing field(s): {', '.join(missing)}"]
        errors = []
        for name, check in self.fields.items():
            problem = check(record[name])
            if problem:
                errors.append(f"{name} {problem}")
        return errors


ORDERS_V1 = Schema(
    name="orders_v1",
    fields={
        "order_id": _text(64),
        "sku": _text(64),
        "quantity": _positive_int,
        "unit_price": _money,
        "currency": _currency,
    },
)

SCHEMAS: dict[str, Schema] = {ORDERS_V1.name: ORDERS_V1}


def validate_content(schema_name: str, filename: str, content: bytes) -> list[str]:
    """Return a list of human-readable problems; an empty list means the file is valid."""
    schema = SCHEMAS.get(schema_name)
    if schema is None:
        return [f"unknown schema '{schema_name}'"]
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "csv":
        return _validate_csv(schema, content)
    if extension == "json":
        return _validate_json(schema, content)
    return [f"unsupported file type '.{extension}' for schema {schema.name}"]


def _decode(content: bytes) -> str | None:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _validate_csv(schema: Schema, content: bytes) -> list[str]:
    text = _decode(content)
    if text is None:
        return ["file is not valid UTF-8"]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = reader.fieldnames
    if not header:
        return ["missing header row"]
    missing = [name for name in schema.fields if name not in header]
    if missing:
        return [f"missing column(s): {', '.join(missing)}"]

    errors: list[str] = []
    rows = 0
    try:
        for row in reader:
            rows += 1
            line = reader.line_num
            if None in row:
                errors.append(f"line {line}: more values than columns")
            elif any(value is None for value in row.values()):
                errors.append(f"line {line}: fewer values than columns")
            else:
                errors.extend(f"line {line}: {problem}" for problem in schema.check_record(row))
    except csv.Error as exc:
        errors.append(f"malformed CSV: {exc}")
    if rows == 0 and not errors:
        errors.append("no data rows")
    return errors


def _validate_json(schema: Schema, content: bytes) -> list[str]:
    text = _decode(content)
    if text is None:
        return ["file is not valid UTF-8"]
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc.msg} (line {exc.lineno})"]
    if not isinstance(document, list):
        return ["top-level value must be an array of records"]
    if not document:
        return ["no records"]

    errors: list[str] = []
    for index, record in enumerate(document):
        if not isinstance(record, dict):
            errors.append(f"record {index}: must be an object")
            continue
        errors.extend(f"record {index}: {problem}" for problem in schema.check_record(record))
    return errors


def summarize(errors: list[str]) -> str:
    shown = "; ".join(errors[:MAX_REPORTED_ERRORS])
    hidden = len(errors) - MAX_REPORTED_ERRORS
    return f"{shown} (+{hidden} more)" if hidden > 0 else shown

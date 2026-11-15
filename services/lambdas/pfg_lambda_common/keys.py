"""Object key layout of the transfer bucket.

inbound/<partner>/<relative path>                         partner uploads
processed/<partner>/<yyyy>/<mm>/<dd>/<relative path>      accepted files
quarantine/<partner>/<yyyy>/<mm>/<dd>/<relative path>     rejected files
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

INBOUND_PREFIX = "inbound/"
PROCESSED_PREFIX = "processed/"
QUARANTINE_PREFIX = "quarantine/"

# Same rule as the pfg CLI: lowercase letters, digits and inner dashes.
PARTNER_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


class InvalidKeyError(ValueError):
    """The object key does not follow inbound/<partner>/<file>."""


@dataclass(frozen=True)
class InboundKey:
    partner_id: str
    relative_path: str

    @property
    def filename(self) -> str:
        return self.relative_path.rsplit("/", 1)[-1]


def parse_inbound_key(key: str) -> InboundKey:
    if not key.startswith(INBOUND_PREFIX):
        raise InvalidKeyError(f"key is not under {INBOUND_PREFIX}: {key!r}")
    partner_id, separator, relative_path = key[len(INBOUND_PREFIX) :].partition("/")
    if not separator or not relative_path or relative_path.endswith("/"):
        raise InvalidKeyError(f"key does not name a file below {INBOUND_PREFIX}<partner>/: {key!r}")
    if not PARTNER_ID_PATTERN.fullmatch(partner_id):
        raise InvalidKeyError(f"invalid partner id in key: {partner_id!r}")
    if any(part in ("", ".", "..") for part in relative_path.split("/")):
        raise InvalidKeyError(f"key contains an empty or relative path segment: {key!r}")
    return InboundKey(partner_id=partner_id, relative_path=relative_path)


def destination_key(prefix: str, inbound: InboundKey, received_at: datetime) -> str:
    """Date-partitioned destination for a file, e.g. processed/acme/2026/11/15/orders.csv."""
    if prefix not in (PROCESSED_PREFIX, QUARANTINE_PREFIX):
        raise ValueError(f"unexpected destination prefix: {prefix!r}")
    return f"{prefix}{inbound.partner_id}/{received_at:%Y/%m/%d}/{inbound.relative_path}"


def transfer_id_for(bucket: str, key: str, version_id: str, etag: str, sequencer: str = "") -> str:
    """Deterministic id of one uploaded object version (ADR-004).

    The same S3 event delivered twice yields the same id, so the conditional
    write in the state machine turns the duplicate into a no-op. A partner
    re-sending an identical file creates a new object version, hence a new id.
    """
    material = "\n".join((bucket, key, version_id, etag, "" if version_id else sequencer))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

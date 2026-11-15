"""Partner lifecycle: DynamoDB registry + S3 prefix + SFTPGo user.

The DynamoDB record is the source of truth. The SFTPGo user is always rebuilt
from it (declarative reconcile), so re-running a command repairs drift.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from botocore.exceptions import ClientError

from pfg.config import KNOWN_SCHEMAS, Settings
from pfg.keys import fingerprint, normalize_public_key

STATUS_ACTIVE = "ACTIVE"
STATUS_DISABLED = "DISABLED"

# Same rule as the pipeline (services/lambdas/pfg_lambda_common/keys.py).
PARTNER_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")

# Every login method except plain public key.
DENIED_LOGIN_METHODS = [
    "password",
    "password-over-SSH",
    "keyboard-interactive",
    "publickey+password",
    "publickey+keyboard-interactive",
    "TLSCertificate",
    "TLSCertificate+password",
]
# SFTP only for now; FTPS is a later, optional step (PLAN.md cut line).
DENIED_PROTOCOLS = ["FTP", "DAV", "HTTP"]
# Partners can drop files and create folders; they cannot read, rename or delete.
PARTNER_PERMISSIONS = ["list", "upload", "overwrite", "create_dirs"]


class PartnerError(Exception):
    pass


class PartnerExistsError(PartnerError):
    pass


class PartnerNotFoundError(PartnerError):
    pass


class InvalidPartnerError(PartnerError):
    pass


class SftpGo(Protocol):
    def upsert_user(self, user: dict[str, Any]) -> str: ...


@dataclass(frozen=True)
class PartnerSpec:
    partner_id: str
    display_name: str
    public_key: str
    allowed_patterns: tuple[str, ...]
    max_file_size_bytes: int
    schema: str


@dataclass(frozen=True)
class CreateResult:
    created: bool
    fingerprint: str
    sftpgo: str


def validate_spec(spec: PartnerSpec) -> PartnerSpec:
    if not PARTNER_ID_PATTERN.fullmatch(spec.partner_id):
        raise InvalidPartnerError(
            "partner id must be 1-32 lowercase letters, digits or inner dashes"
        )
    if not spec.allowed_patterns:
        raise InvalidPartnerError("at least one --pattern is required")
    if any("/" in pattern for pattern in spec.allowed_patterns):
        raise InvalidPartnerError("patterns match file names and cannot contain '/'")
    if spec.max_file_size_bytes <= 0:
        raise InvalidPartnerError("--max-size must be positive")
    if spec.schema not in KNOWN_SCHEMAS:
        raise InvalidPartnerError(f"unknown schema {spec.schema!r}; known: {KNOWN_SCHEMAS}")
    return PartnerSpec(
        partner_id=spec.partner_id,
        display_name=spec.display_name.strip() or spec.partner_id,
        public_key=normalize_public_key(spec.public_key),
        allowed_patterns=tuple(dict.fromkeys(spec.allowed_patterns)),
        max_file_size_bytes=spec.max_file_size_bytes,
        schema=spec.schema,
    )


def sftpgo_user(item: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """SFTPGo user for a registry record: key-only SFTP, jailed to inbound/<partner>/."""
    partner_id = item["partner_id"]
    return {
        "username": partner_id,
        "status": 1 if item["status"] == STATUS_ACTIVE else 0,
        "description": f"{item['name']} (managed by pfg)",
        "public_keys": [item["public_key"]],
        "permissions": {"/": PARTNER_PERMISSIONS},
        "max_sessions": 5,
        "filesystem": {
            "provider": 1,  # S3-compatible object storage
            "s3config": {
                "bucket": settings.transfer_bucket,
                "region": settings.sftpgo_s3_region,
                "endpoint": settings.sftpgo_s3_endpoint,
                "access_key": settings.sftpgo_s3_access_key,
                "access_secret": {"status": "Plain", "payload": settings.sftpgo_s3_secret_key},
                "key_prefix": f"inbound/{partner_id}/",
                "force_path_style": True,
            },
        },
        "filters": {
            "denied_login_methods": DENIED_LOGIN_METHODS,
            "denied_protocols": DENIED_PROTOCOLS,
            "max_upload_file_size": settings.max_upload_bytes,
            # Must stay False: with an S3 backend SFTPGo buffers uploads in the user's
            # local home dir, which it only creates at login when fs checks are on.
            "disable_fs_checks": False,
        },
    }


class PartnerService:
    def __init__(
        self,
        *,
        table: Any,
        s3: Any,
        sftpgo: SftpGo,
        settings: Settings,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.table = table
        self.s3 = s3
        self.sftpgo = sftpgo
        self.settings = settings
        self.now = now

    def _timestamp(self) -> str:
        return self.now().isoformat(timespec="seconds").replace("+00:00", "Z")

    def get(self, partner_id: str) -> dict[str, Any]:
        item = self.table.get_item(Key={"partner_id": partner_id}, ConsistentRead=True).get("Item")
        if not item:
            raise PartnerNotFoundError(f"partner {partner_id!r} does not exist")
        return item

    def create(self, spec: PartnerSpec, *, if_not_exists: bool = False) -> CreateResult:
        spec = validate_spec(spec)
        key_fingerprint = fingerprint(spec.public_key)
        now = self._timestamp()
        item = {
            "partner_id": spec.partner_id,
            "name": spec.display_name,
            "status": STATUS_ACTIVE,
            "allowed_patterns": list(spec.allowed_patterns),
            "max_file_size_bytes": spec.max_file_size_bytes,
            "schema": spec.schema,
            "public_key": spec.public_key,
            "key_fingerprint": key_fingerprint,
            "created_at": now,
            "updated_at": now,
        }
        created = True
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(partner_id)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            if not if_not_exists:
                raise PartnerExistsError(f"partner {spec.partner_id!r} already exists") from None
            item = self.get(spec.partner_id)
            if item.get("key_fingerprint") != key_fingerprint:
                raise PartnerExistsError(
                    f"partner {spec.partner_id!r} exists with a different key; use rotate-key"
                ) from None
            created = False

        # Visible "folder" for the partner; the pipeline ignores keys ending in '/'.
        self.s3.put_object(
            Bucket=self.settings.transfer_bucket, Key=f"inbound/{spec.partner_id}/", Body=b""
        )
        outcome = self.sftpgo.upsert_user(sftpgo_user(item, self.settings))
        return CreateResult(created=created, fingerprint=key_fingerprint, sftpgo=outcome)

    def rotate_key(self, partner_id: str, public_key: str) -> str:
        """Replace the partner's key. The old key stops working immediately."""
        public_key = normalize_public_key(public_key)
        item = self.get(partner_id)
        new_fingerprint = fingerprint(public_key)
        if new_fingerprint == item.get("key_fingerprint"):
            raise InvalidPartnerError("the new key is the same as the current key")
        now = self._timestamp()
        item = {
            **item,
            "public_key": public_key,
            "key_fingerprint": new_fingerprint,
            "key_rotated_at": now,
            "updated_at": now,
        }
        # SFTPGo first: once it returns, the old key is refused and sessions are closed.
        self.sftpgo.upsert_user(sftpgo_user(item, self.settings))
        self.table.update_item(
            Key={"partner_id": partner_id},
            UpdateExpression="SET public_key = :key, key_fingerprint = :fp, "
            "key_rotated_at = :now, updated_at = :now",
            ExpressionAttributeValues={":key": public_key, ":fp": new_fingerprint, ":now": now},
            ConditionExpression="attribute_exists(partner_id)",
        )
        return new_fingerprint

    def set_status(self, partner_id: str, status: str) -> None:
        """Disable blocks SFTP logins and makes Validate reject new files."""
        if status not in (STATUS_ACTIVE, STATUS_DISABLED):
            raise InvalidPartnerError(f"invalid status {status!r}")
        item = self.get(partner_id)
        now = self._timestamp()
        self.table.update_item(
            Key={"partner_id": partner_id},
            UpdateExpression="SET #status = :status, updated_at = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": status, ":now": now},
            ConditionExpression="attribute_exists(partner_id)",
        )
        self.sftpgo.upsert_user(sftpgo_user({**item, "status": status}, self.settings))

    def list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {}
        while True:
            page = self.table.scan(**kwargs)
            items.extend(page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return sorted(items, key=lambda item: item["partner_id"])

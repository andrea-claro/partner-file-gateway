"""Settings, read from the environment (see docker-compose.yml, service "tools")."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Mirrors services/lambdas/validate/schemas.py (a unit test keeps them in sync).
KNOWN_SCHEMAS = ("orders_v1",)


@dataclass(frozen=True)
class Settings:
    partners_table: str = "partners"
    transfer_bucket: str = "pfg-transfer"
    sftpgo_url: str = "http://localhost:8080"
    sftpgo_admin_username: str = ""
    sftpgo_admin_password: str = ""
    # How SFTPGo itself reaches S3. On LocalStack these are the fixed dummy
    # credentials; on real AWS SFTPGo would use an IAM role instead.
    sftpgo_s3_endpoint: str = "http://localstack:4566"
    sftpgo_s3_region: str = "eu-central-2"
    sftpgo_s3_access_key: str = "test"
    sftpgo_s3_secret_key: str = "test"  # noqa: S105 - LocalStack dummy value, not a secret
    keys_dir: Path = Path(".secrets/partners")
    # Hard cap enforced by SFTPGo itself; per-partner limits are checked by Validate.
    max_upload_bytes: int = 100 * 1024 * 1024

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            partners_table=env.get("PFG_PARTNERS_TABLE", defaults.partners_table),
            transfer_bucket=env.get("PFG_TRANSFER_BUCKET", defaults.transfer_bucket),
            sftpgo_url=env.get("SFTPGO_URL", defaults.sftpgo_url),
            sftpgo_admin_username=env.get("SFTPGO_ADMIN_USERNAME", ""),
            sftpgo_admin_password=env.get("SFTPGO_ADMIN_PASSWORD", ""),
            sftpgo_s3_endpoint=env.get("PFG_SFTPGO_S3_ENDPOINT", defaults.sftpgo_s3_endpoint),
            sftpgo_s3_region=env.get("AWS_REGION", defaults.sftpgo_s3_region),
            sftpgo_s3_access_key=env.get("PFG_SFTPGO_S3_ACCESS_KEY", defaults.sftpgo_s3_access_key),
            sftpgo_s3_secret_key=env.get("PFG_SFTPGO_S3_SECRET_KEY", defaults.sftpgo_s3_secret_key),
            keys_dir=Path(env.get("PFG_KEYS_DIR", str(defaults.keys_dir))),
        )

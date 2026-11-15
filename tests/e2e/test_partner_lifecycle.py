"""Phase 3 acceptance: onboarding, key rotation and disabling against the live stack."""

import secrets
from pathlib import Path

import boto3
import paramiko
import pytest

from pfg.config import Settings
from pfg.keys import generate_keypair, write_private_key
from pfg.service import STATUS_DISABLED, PartnerService, PartnerSpec
from pfg.sftpgo import SftpGoClient
from tests.live import BUCKET, SAMPLES, require_stack, sftp_client, sftp_upload, wait_for_transfer

pytestmark = pytest.mark.live


@pytest.fixture
def service():
    require_stack()
    settings = Settings.from_env()
    return PartnerService(
        table=boto3.resource("dynamodb").Table(settings.partners_table),
        s3=boto3.client("s3"),
        sftpgo=SftpGoClient(
            settings.sftpgo_url, settings.sftpgo_admin_username, settings.sftpgo_admin_password
        ),
        settings=settings,
    )


def new_key(tmp_path: Path, name: str) -> tuple[Path, str]:
    private_bytes, public_key = generate_keypair()
    path = tmp_path / name
    write_private_key(path, private_bytes)
    return path, public_key


def onboard(service, tmp_path) -> tuple[str, Path]:
    partner_id = f"e2e-{secrets.token_hex(3)}"
    key_path, public_key = new_key(tmp_path, "first")
    service.create(
        PartnerSpec(
            partner_id=partner_id,
            display_name="E2E partner",
            public_key=public_key,
            allowed_patterns=("orders_*.csv",),
            max_file_size_bytes=1024 * 1024,
            schema="orders_v1",
        )
    )
    return partner_id, key_path


def test_new_partner_can_upload_after_one_command(service, tmp_path):
    partner_id, key_path = onboard(service, tmp_path)
    sample = SAMPLES / "valid" / "orders_basic.csv"
    sftp_upload(partner_id, key_path, "orders_first.csv", sample.read_bytes())
    item = wait_for_transfer(f"inbound/{partner_id}/orders_first.csv")
    assert item["status"] == "DELIVERED"


def test_rotated_key_refuses_the_old_one(service, tmp_path):
    partner_id, old_key = onboard(service, tmp_path)
    sftp_client(partner_id, old_key).close()  # old key works

    new_key_path, new_public = new_key(tmp_path, "second")
    service.rotate_key(partner_id, new_public)

    with pytest.raises(paramiko.AuthenticationException):
        sftp_client(partner_id, old_key)
    sftp_client(partner_id, new_key_path).close()


def test_disabled_partner_cannot_log_in_and_files_are_rejected(service, tmp_path):
    partner_id, key_path = onboard(service, tmp_path)
    service.set_status(partner_id, STATUS_DISABLED)

    with pytest.raises(paramiko.AuthenticationException):
        sftp_client(partner_id, key_path)

    # A file that reaches S3 anyway (e.g. uploaded just before disabling) is rejected.
    key = f"inbound/{partner_id}/orders_late.csv"
    body = (SAMPLES / "valid" / "orders_basic.csv").read_bytes()
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=body)
    item = wait_for_transfer(key)
    assert item["status"] == "REJECTED"
    assert "disabled" in item["reason"]

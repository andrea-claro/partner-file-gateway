"""Keep the live stack (and the public dashboard) clean: remove the throwaway
partners that e2e runs create, before and after the session."""

import boto3
import pytest
from boto3.dynamodb.conditions import Attr

from pfg.config import Settings
from pfg.sftpgo import SftpGoClient
from tests.live import require_stack

E2E_PREFIX = "e2e-"


def purge_e2e_partners() -> None:
    settings = Settings.from_env()
    table = boto3.resource("dynamodb").Table(settings.partners_table)
    sftpgo = SftpGoClient(
        settings.sftpgo_url, settings.sftpgo_admin_username, settings.sftpgo_admin_password
    )
    kwargs = {
        "FilterExpression": Attr("partner_id").begins_with(E2E_PREFIX),
        "ProjectionExpression": "partner_id",
    }
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            sftpgo.delete_user(item["partner_id"])
            table.delete_item(Key={"partner_id": item["partner_id"]})
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


@pytest.fixture(scope="session", autouse=True)
def _clean_e2e_partners():
    require_stack()
    purge_e2e_partners()
    yield
    purge_e2e_partners()

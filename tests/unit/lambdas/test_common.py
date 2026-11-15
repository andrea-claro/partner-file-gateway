import io
import json
from datetime import UTC, datetime

import pytest

from pfg_lambda_common.keys import (
    PROCESSED_PREFIX,
    QUARANTINE_PREFIX,
    InvalidKeyError,
    destination_key,
    parse_inbound_key,
    transfer_id_for,
)
from pfg_lambda_common.log import JsonLogger
from pfg_lambda_common.s3move import ascii_metadata


class TestParseInboundKey:
    def test_simple_file(self):
        key = parse_inbound_key("inbound/acme/orders_1.csv")
        assert key.partner_id == "acme"
        assert key.relative_path == "orders_1.csv"
        assert key.filename == "orders_1.csv"

    def test_nested_file(self):
        key = parse_inbound_key("inbound/acme-2/2026/batch/orders_1.csv")
        assert key.partner_id == "acme-2"
        assert key.relative_path == "2026/batch/orders_1.csv"
        assert key.filename == "orders_1.csv"

    @pytest.mark.parametrize(
        "key",
        [
            "processed/acme/orders.csv",  # wrong prefix
            "inbound/orders.csv",  # no partner folder
            "inbound/acme/",  # folder marker
            "inbound/acme/sub/",  # nested folder marker
            "inbound/ACME/orders.csv",  # partner ids are lowercase
            "inbound/-acme/orders.csv",  # must start with a letter or digit
            "inbound/acme/../other/orders.csv",  # path traversal
            "inbound/acme//orders.csv",  # empty segment
        ],
    )
    def test_rejects_invalid_keys(self, key):
        with pytest.raises(InvalidKeyError):
            parse_inbound_key(key)


def test_destination_key_is_date_partitioned():
    inbound = parse_inbound_key("inbound/acme/batch/orders_1.csv")
    at = datetime(2026, 11, 5, 23, 59, tzinfo=UTC)
    assert destination_key(PROCESSED_PREFIX, inbound, at) == (
        "processed/acme/2026/11/05/batch/orders_1.csv"
    )
    assert destination_key(QUARANTINE_PREFIX, inbound, at) == (
        "quarantine/acme/2026/11/05/batch/orders_1.csv"
    )


def test_destination_key_rejects_other_prefixes():
    inbound = parse_inbound_key("inbound/acme/orders_1.csv")
    with pytest.raises(ValueError, match="unexpected destination prefix"):
        destination_key("inbound/", inbound, datetime.now(UTC))


class TestTransferId:
    def test_is_deterministic(self):
        args = ("pfg-transfer", "inbound/acme/a.csv", "v1", "etag")
        assert transfer_id_for(*args) == transfer_id_for(*args)
        assert len(transfer_id_for(*args)) == 32

    def test_new_version_of_same_content_is_a_new_transfer(self):
        first = transfer_id_for("b", "inbound/acme/a.csv", "v1", "same-etag")
        second = transfer_id_for("b", "inbound/acme/a.csv", "v2", "same-etag")
        assert first != second

    def test_sequencer_is_used_only_without_version_id(self):
        assert transfer_id_for("b", "k", "v1", "e", "seq1") == transfer_id_for(
            "b", "k", "v1", "e", "seq2"
        )
        assert transfer_id_for("b", "k", "", "e", "seq1") != transfer_id_for(
            "b", "k", "", "e", "seq2"
        )


def test_json_logger_emits_one_json_line_with_context(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    stream = io.StringIO()
    log = JsonLogger("test", stream).bind(transfer_id="abc")
    log.debug("hidden")
    log.info("visible", size=3)
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "visible"
    assert record["transfer_id"] == "abc"
    assert record["component"] == "test"
    assert record["level"] == "INFO"
    assert record["size"] == 3


def test_ascii_metadata_is_ascii_and_bounded():
    value = ascii_metadata("Prüfung fehlgeschlagen\n" + "x" * 1000)
    value.encode("ascii")  # does not raise
    assert "\n" not in value
    assert len(value) == 512

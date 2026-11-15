import pytest

from tests.unit.conftest import BUCKET, SAMPLES, active_partner
from validate.handler import handle, load_partner
from validate.logic import Partner, validate_transfer
from validate.schemas import MAX_REPORTED_ERRORS, summarize, validate_content

DEFAULT_MAX = 10 * 1024 * 1024


def metadata_for(filename: str, size: int, partner_id: str = "acme") -> dict:
    return {
        "transfer_id": "t" * 32,
        "bucket": BUCKET,
        "key": f"inbound/{partner_id}/{filename}",
        "version_id": "",
        "partner_id": partner_id,
        "filename": filename,
        "size": size,
    }


def run(filename: str, content: bytes, partner: Partner | None) -> tuple[bool, str]:
    result = validate_transfer(
        metadata_for(filename, len(content)),
        partner,
        lambda: content,
        default_max_size=DEFAULT_MAX,
    )
    return result.valid, result.reason


def never_read() -> bytes:
    raise AssertionError("the file body must not be read for this check")


ACME = Partner.from_item(active_partner())


class TestHappyPath:
    @pytest.mark.parametrize("sample", sorted((SAMPLES / "valid").iterdir()), ids=lambda p: p.name)
    def test_valid_samples_are_accepted(self, sample):
        assert run(sample.name, sample.read_bytes(), ACME) == (True, "")


class TestRejections:
    def test_unknown_partner(self):
        result = validate_transfer(
            metadata_for("orders_1.csv", 10), None, never_read, default_max_size=DEFAULT_MAX
        )
        assert not result.valid
        assert result.reason == "unknown partner 'acme'"

    def test_disabled_partner(self):
        disabled = Partner.from_item(active_partner(status="DISABLED"))
        result = validate_transfer(
            metadata_for("orders_1.csv", 10), disabled, never_read, default_max_size=DEFAULT_MAX
        )
        assert not result.valid
        assert result.reason == "partner 'acme' is disabled"

    def test_wrong_file_name_pattern(self):
        sample = SAMPLES / "invalid" / "invoice_2026.pdf.txt"
        valid, reason = run(sample.name, sample.read_bytes(), ACME)
        assert not valid
        assert "does not match the allowed patterns (orders_*.csv, orders_*.json)" in reason

    def test_patterns_are_case_sensitive(self):
        valid, reason = run("ORDERS_1.CSV", b"x", ACME)
        assert not valid
        assert "does not match" in reason

    def test_empty_file(self):
        result = validate_transfer(
            metadata_for("orders_1.csv", 0), ACME, never_read, default_max_size=DEFAULT_MAX
        )
        assert (result.valid, result.reason) == (False, "file is empty")

    def test_oversize_uses_partner_limit(self):
        result = validate_transfer(
            metadata_for("orders_1.csv", 1024 * 1024 + 1),
            ACME,
            never_read,
            default_max_size=DEFAULT_MAX,
        )
        assert not result.valid
        assert result.reason == "file is 1048577 bytes, the limit is 1048576 bytes"

    def test_oversize_falls_back_to_default_limit(self):
        no_limit = Partner.from_item(active_partner(max_file_size_bytes=None))
        result = validate_transfer(
            metadata_for("orders_1.csv", 101), no_limit, never_read, default_max_size=100
        )
        assert result.reason == "file is 101 bytes, the limit is 100 bytes"

    @pytest.mark.parametrize(
        ("sample", "expected"),
        [
            ("orders_missing_currency.csv", "missing column(s): currency"),
            ("orders_header_only.csv", "no data rows"),
            ("orders_broken.json", "invalid JSON"),
            ("orders_negative_quantity.json", "record 0: quantity must be a positive integer"),
        ],
    )
    def test_bad_schema(self, sample, expected):
        content = (SAMPLES / "invalid" / sample).read_bytes()
        valid, reason = run(sample, content, ACME)
        assert not valid
        assert reason.startswith("schema orders_v1: ")
        assert expected in reason


class TestSchemaDetails:
    def test_reports_line_numbers_for_csv(self):
        content = b"order_id,sku,quantity,unit_price,currency\nA,B,1,1.00,CHF\nA,B,0,1.999,chf\n"
        errors = validate_content("orders_v1", "orders.csv", content)
        assert errors == [
            "line 3: quantity must be a positive integer",
            "line 3: unit_price must be a non-negative amount with at most 2 decimals",
            "line 3: currency must be a 3-letter ISO 4217 code such as CHF",
        ]

    def test_ragged_csv_rows(self):
        content = b"order_id,sku,quantity,unit_price,currency\nA,B,1,1.00\nA,B,1,1.00,CHF,extra\n"
        errors = validate_content("orders_v1", "orders.csv", content)
        assert errors == ["line 2: fewer values than columns", "line 3: more values than columns"]

    def test_json_must_be_an_array_of_objects(self):
        assert validate_content("orders_v1", "o.json", b'{"order_id": "A"}') == [
            "top-level value must be an array of records"
        ]
        assert validate_content("orders_v1", "o.json", b"[1]") == ["record 0: must be an object"]
        assert validate_content("orders_v1", "o.json", b"[]") == ["no records"]

    def test_json_booleans_are_not_numbers(self):
        record = b'[{"order_id":"A","sku":"B","quantity":true,"unit_price":false,"currency":"CHF"}]'
        errors = validate_content("orders_v1", "o.json", record)
        assert errors == [
            "record 0: quantity must be a positive integer",
            "record 0: unit_price must be a non-negative amount with at most 2 decimals",
        ]

    def test_non_utf8_and_unknown_types(self):
        assert validate_content("orders_v1", "o.csv", b"\xff\xfe\x00") == [
            "file is not valid UTF-8"
        ]
        assert validate_content("orders_v1", "o.xml", b"<a/>") == [
            "unsupported file type '.xml' for schema orders_v1"
        ]
        assert validate_content("nope", "o.csv", b"") == ["unknown schema 'nope'"]

    def test_summarize_caps_the_number_of_errors(self):
        errors = [f"e{i}" for i in range(MAX_REPORTED_ERRORS + 3)]
        assert summarize(errors) == "e0; e1; e2; e3; e4 (+3 more)"


class TestHandler:
    def test_reads_partner_and_object_from_aws(self, s3, partners_table):
        partners_table.put_item(Item=active_partner())
        body = (SAMPLES / "valid" / "orders_basic.csv").read_bytes()
        version = s3.put_object(Bucket=BUCKET, Key="inbound/acme/orders_basic.csv", Body=body)[
            "VersionId"
        ]
        metadata = {**metadata_for("orders_basic.csv", len(body)), "version_id": version}

        output = handle(
            {"metadata": metadata},
            s3=s3,
            partners_table=partners_table,
            default_max_size=DEFAULT_MAX,
        )
        assert output == {"valid": True, "reason": ""}

    def test_bad_schema_from_aws(self, s3, partners_table):
        partners_table.put_item(Item=active_partner())
        body = (SAMPLES / "invalid" / "orders_missing_currency.csv").read_bytes()
        s3.put_object(Bucket=BUCKET, Key="inbound/acme/orders_missing_currency.csv", Body=body)
        output = handle(
            {"metadata": metadata_for("orders_missing_currency.csv", len(body))},
            s3=s3,
            partners_table=partners_table,
            default_max_size=DEFAULT_MAX,
        )
        assert output == {
            "valid": False,
            "reason": "schema orders_v1: missing column(s): currency",
        }

    def test_load_partner_converts_dynamodb_types(self, partners_table):
        partners_table.put_item(Item=active_partner())
        partner = load_partner(partners_table, "acme")
        assert partner == ACME
        assert isinstance(partner.max_file_size_bytes, int)
        assert load_partner(partners_table, "missing") is None

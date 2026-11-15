import base64
import json
import stat
from typing import Any

import boto3
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from typer.testing import CliRunner

from pfg import app as cli
from pfg.config import KNOWN_SCHEMAS, Settings
from pfg.keys import InvalidPublicKeyError, fingerprint, generate_keypair, normalize_public_key
from pfg.service import PartnerService
from pfg.sftpgo import SftpGoClient, SftpGoError
from tests.unit.conftest import BUCKET, REGION
from validate.schemas import SCHEMAS

runner = CliRunner()


class FakeSftpGo:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}

    def upsert_user(self, user: dict[str, Any]) -> str:
        outcome = "updated" if user["username"] in self.users else "created"
        self.users[user["username"]] = user
        return outcome


@pytest.fixture
def env(s3, partners_table, tmp_path, monkeypatch):
    monkeypatch.setenv("PFG_KEYS_DIR", str(tmp_path / "keys"))
    sftpgo = FakeSftpGo()
    service = PartnerService(
        table=partners_table,
        s3=boto3.client("s3", region_name=REGION),
        sftpgo=sftpgo,
        settings=Settings.from_env(),
    )
    monkeypatch.setattr(cli, "build_service", lambda settings: service)
    return {"sftpgo": sftpgo, "table": partners_table, "s3": s3, "keys": tmp_path / "keys"}


def invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def public_key_file(tmp_path, name="partner.pub"):
    _, public_key = generate_keypair()
    path = tmp_path / name
    path.write_text(public_key + " partner@example\n")
    return path, public_key


class TestCreate:
    def test_generate_key_onboards_partner(self, env):
        result = invoke(
            "partner", "create", "--name", "acme", "--generate-key", "--pattern", "orders_*.csv"
        )
        assert result.exit_code == 0, result.output

        item = env["table"].get_item(Key={"partner_id": "acme"})["Item"]
        assert item["status"] == "ACTIVE"
        assert item["allowed_patterns"] == ["orders_*.csv"]
        assert item["schema"] == "orders_v1"
        assert item["key_fingerprint"].startswith("SHA256:")

        # S3 prefix exists
        env["s3"].head_object(Bucket=BUCKET, Key="inbound/acme/")

        user = env["sftpgo"].users["acme"]
        assert user["status"] == 1
        assert user["public_keys"] == [item["public_key"]]
        assert user["filesystem"]["s3config"]["key_prefix"] == "inbound/acme/"
        assert user["filesystem"]["s3config"]["bucket"] == "pfg-transfer"
        assert "password" in user["filters"]["denied_login_methods"]
        assert "publickey" not in user["filters"]["denied_login_methods"]
        assert set(user["filters"]["denied_protocols"]) == {"FTP", "DAV", "HTTP"}
        # Regression: with fs checks disabled SFTPGo never creates the local upload
        # buffer dir for S3 users and every upload fails with "no such file".
        assert user["filters"]["disable_fs_checks"] is False
        assert "download" not in user["permissions"]["/"]
        assert "delete" not in user["permissions"]["/"]

        private = env["keys"] / "acme" / "id_ed25519"
        assert stat.S_IMODE(private.stat().st_mode) == 0o600
        assert private.read_bytes().startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----")
        assert "PRIVATE KEY" not in result.output
        assert fingerprint(item["public_key"]) == item["key_fingerprint"]

    def test_pubkey_from_partner(self, env, tmp_path):
        path, public_key = public_key_file(tmp_path)
        result = invoke("partner", "create", "--name", "globex", "--pubkey", str(path))
        assert result.exit_code == 0, result.output
        item = env["table"].get_item(Key={"partner_id": "globex"})["Item"]
        assert item["public_key"] == public_key  # comment dropped
        assert item["allowed_patterns"] == ["*.csv", "*.json"]
        assert not (env["keys"] / "globex").exists()

    def test_duplicate_is_refused(self, env, tmp_path):
        path, _ = public_key_file(tmp_path)
        assert invoke("partner", "create", "--name", "acme", "--pubkey", str(path)).exit_code == 0
        result = invoke("partner", "create", "--name", "acme", "--pubkey", str(path))
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_if_not_exists_reconciles_with_same_key(self, env, tmp_path):
        path, _ = public_key_file(tmp_path)
        assert invoke("partner", "create", "--name", "acme", "--pubkey", str(path)).exit_code == 0
        env["sftpgo"].users.clear()  # simulate a wiped SFTPGo database
        result = invoke(
            "partner", "create", "--name", "acme", "--pubkey", str(path), "--if-not-exists"
        )
        assert result.exit_code == 0, result.output
        assert "already existed, reconciled" in result.output
        assert "acme" in env["sftpgo"].users

    def test_if_not_exists_refuses_a_different_key(self, env, tmp_path):
        first, _ = public_key_file(tmp_path, "a.pub")
        second, _ = public_key_file(tmp_path, "b.pub")
        assert invoke("partner", "create", "--name", "acme", "--pubkey", str(first)).exit_code == 0
        result = invoke(
            "partner", "create", "--name", "acme", "--pubkey", str(second), "--if-not-exists"
        )
        assert result.exit_code == 1
        assert "different key" in result.output

    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--name", "Bad_Name", "--generate-key"], "partner id must be"),
            (["--name", "acme"], "exactly one of --pubkey or --generate-key"),
            (["--name", "acme", "--generate-key", "--schema", "nope"], "unknown schema"),
            (["--name", "acme", "--generate-key", "--pattern", "a/b.csv"], "cannot contain '/'"),
            (
                ["--name", "acme", "--generate-key", "--max-size", "0"],
                "--max-size must be positive",
            ),
        ],
    )
    def test_invalid_input(self, env, args, message):
        result = invoke("partner", "create", *args)
        assert result.exit_code == 1
        assert message in result.output
        assert env["sftpgo"].users == {}

    def test_refuses_to_overwrite_an_existing_private_key(self, env):
        assert invoke("partner", "create", "--name", "acme", "--generate-key").exit_code == 0
        env["table"].delete_item(Key={"partner_id": "acme"})
        result = invoke("partner", "create", "--name", "acme", "--generate-key")
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestRotateKey:
    def test_generated_key_replaces_the_old_one(self, env):
        assert invoke("partner", "create", "--name", "acme", "--generate-key").exit_code == 0
        private = env["keys"] / "acme" / "id_ed25519"
        old_private = private.read_bytes()
        old_fp = env["table"].get_item(Key={"partner_id": "acme"})["Item"]["key_fingerprint"]

        result = invoke("partner", "rotate-key", "--name", "acme", "--generate-key")
        assert result.exit_code == 0, result.output

        item = env["table"].get_item(Key={"partner_id": "acme"})["Item"]
        assert item["key_fingerprint"] != old_fp
        assert "key_rotated_at" in item
        assert env["sftpgo"].users["acme"]["public_keys"] == [item["public_key"]]
        assert private.read_bytes() != old_private
        assert stat.S_IMODE(private.stat().st_mode) == 0o600
        assert not private.with_name("id_ed25519.new").exists()

    def test_same_key_is_refused(self, env, tmp_path):
        path, _ = public_key_file(tmp_path)
        assert invoke("partner", "create", "--name", "acme", "--pubkey", str(path)).exit_code == 0
        result = invoke("partner", "rotate-key", "--name", "acme", "--pubkey", str(path))
        assert result.exit_code == 1
        assert "same as the current key" in result.output

    def test_unknown_partner_leaves_no_staged_key(self, env):
        result = invoke("partner", "rotate-key", "--name", "ghost", "--generate-key")
        assert result.exit_code == 1
        assert "does not exist" in result.output
        assert not (env["keys"] / "ghost" / "id_ed25519.new").exists()


class TestStatus:
    def test_disable_and_enable(self, env):
        assert invoke("partner", "create", "--name", "acme", "--generate-key").exit_code == 0

        assert invoke("partner", "disable", "--name", "acme").exit_code == 0
        assert env["table"].get_item(Key={"partner_id": "acme"})["Item"]["status"] == "DISABLED"
        assert env["sftpgo"].users["acme"]["status"] == 0

        assert invoke("partner", "enable", "--name", "acme").exit_code == 0
        assert env["table"].get_item(Key={"partner_id": "acme"})["Item"]["status"] == "ACTIVE"
        assert env["sftpgo"].users["acme"]["status"] == 1

    def test_disable_unknown_partner(self, env):
        result = invoke("partner", "disable", "--name", "ghost")
        assert result.exit_code == 1
        assert "does not exist" in result.output


def test_list(env):
    assert invoke("partner", "create", "--name", "zeta", "--generate-key").exit_code == 0
    assert invoke("partner", "create", "--name", "acme", "--generate-key").exit_code == 0
    result = invoke("partner", "list")
    assert result.exit_code == 0
    assert result.output.index("acme") < result.output.index("zeta")


class TestKeys:
    def test_rejects_weak_rsa_and_garbage(self):
        weak = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        weak_text = weak.public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        ).decode()
        with pytest.raises(InvalidPublicKeyError, match="at least 3072"):
            normalize_public_key(weak_text)
        with pytest.raises(InvalidPublicKeyError):
            normalize_public_key("ssh-ed25519 not-base64")
        with pytest.raises(InvalidPublicKeyError):
            normalize_public_key("garbage")

    def test_fingerprint_matches_ssh_keygen_format(self):
        _, public_key = generate_keypair()
        value = fingerprint(public_key)
        assert value.startswith("SHA256:")
        assert not value.endswith("=")
        assert len(base64.b64decode(value[7:] + "=")) == 32


def test_cli_knows_the_same_schemas_as_the_pipeline():
    assert set(KNOWN_SCHEMAS) == set(SCHEMAS)


class TestSftpGoClient:
    def make(self, handler):
        return SftpGoClient(
            "http://sftpgo:8080", "admin", "secret", transport=httpx.MockTransport(handler)
        )

    def test_creates_missing_user_with_bearer_token(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/api/v2/token":
                expected = "Basic " + base64.b64encode(b"admin:secret").decode()
                assert request.headers["Authorization"] == expected
                return httpx.Response(200, json={"access_token": "tok", "expires_at": "x"})
            assert request.headers["Authorization"] == "Bearer tok"
            if request.method == "GET":
                return httpx.Response(404, json={"error": "not found"})
            assert request.method == "POST"
            assert json.loads(request.content)["username"] == "acme"
            return httpx.Response(201, json={})

        assert self.make(handler).upsert_user({"username": "acme"}) == "created"
        assert [c.url.path for c in calls] == [
            "/api/v2/token",
            "/api/v2/users/acme",
            "/api/v2/users",
        ]

    def test_updates_existing_user_and_disconnects_sessions(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v2/token":
                return httpx.Response(200, json={"access_token": "tok"})
            if request.method == "GET":
                return httpx.Response(200, json={"username": "acme"})
            assert request.method == "PUT"
            assert request.url.params["disconnect"] == "1"
            return httpx.Response(200, json={"message": "User updated"})

        assert self.make(handler).upsert_user({"username": "acme"}) == "updated"

    def test_refreshes_an_expired_token_once(self):
        tokens = iter(["old", "new"])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v2/token":
                return httpx.Response(200, json={"access_token": next(tokens)})
            if request.headers["Authorization"] == "Bearer old":
                return httpx.Response(401)
            return httpx.Response(200, json={"username": "acme"})

        assert self.make(handler).get_user("acme") == {"username": "acme"}

    def test_delete_user(self):
        existing = {"acme"}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v2/token":
                return httpx.Response(200, json={"access_token": "tok"})
            assert request.method == "DELETE"
            name = request.url.path.rsplit("/", 1)[-1]
            if name in existing:
                existing.discard(name)
                return httpx.Response(200, json={"message": "User deleted"})
            return httpx.Response(404, json={"error": "not found"})

        client = self.make(handler)
        assert client.delete_user("acme") is True
        assert client.delete_user("acme") is False

    def test_errors_are_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v2/token":
                return httpx.Response(200, json={"access_token": "tok"})
            return httpx.Response(400, json={"error": "invalid public key"})

        with pytest.raises(SftpGoError, match="HTTP 400: invalid public key"):
            self.make(handler).get_user("acme")

    def test_requires_credentials(self):
        with pytest.raises(SftpGoError, match="must be set"):
            SftpGoClient("http://sftpgo:8080", "", "")

"""pfg command line interface (Typer)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import boto3
import typer
from rich.console import Console
from rich.table import Table

from pfg.config import KNOWN_SCHEMAS, Settings
from pfg.keys import generate_keypair, write_private_key, write_public_key
from pfg.service import (
    STATUS_ACTIVE,
    STATUS_DISABLED,
    PartnerError,
    PartnerService,
    PartnerSpec,
)
from pfg.sftpgo import SftpGoClient, SftpGoError

app = typer.Typer(
    no_args_is_help=True,
    help="Partner onboarding and key management for partner-file-gateway.",
)
partner_app = typer.Typer(no_args_is_help=True, help="Create, rotate, disable and list partners.")
app.add_typer(partner_app, name="partner")

console = Console()
err_console = Console(stderr=True)

DEFAULT_PATTERNS = ["*.csv", "*.json"]
DEFAULT_MAX_SIZE = 10 * 1024 * 1024


def build_service(settings: Settings) -> PartnerService:
    """Real clients. boto3 honours AWS_ENDPOINT_URL, which points at LocalStack."""
    return PartnerService(
        table=boto3.resource("dynamodb").Table(settings.partners_table),
        s3=boto3.client("s3"),
        sftpgo=SftpGoClient(
            settings.sftpgo_url, settings.sftpgo_admin_username, settings.sftpgo_admin_password
        ),
        settings=settings,
    )


def _fail(message: str) -> None:
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code=1)


def _key_paths(settings: Settings, partner_id: str) -> tuple[Path, Path]:
    private = settings.keys_dir / partner_id / "id_ed25519"
    return private, private.with_name("id_ed25519.pub")


def _resolve_public_key(
    settings: Settings, partner_id: str, pubkey: Path | None, generate_key: bool
) -> tuple[str, Path | None, bytes | None]:
    """Return (public key, private key path, private key bytes to write later)."""
    if bool(pubkey) == generate_key:
        _fail("pass exactly one of --pubkey or --generate-key")
    if pubkey:
        try:
            return pubkey.read_text(encoding="ascii"), None, None
        except (OSError, UnicodeDecodeError) as exc:
            _fail(f"cannot read {pubkey}: {exc}")
    private_bytes, public_key = generate_keypair()
    private_path, _ = _key_paths(settings, partner_id)
    return public_key, private_path, private_bytes


@partner_app.command("create")
def create(
    name: Annotated[str, typer.Option("--name", help="Partner id: lowercase, digits, dashes.")],
    display_name: Annotated[str, typer.Option(help="Human-readable name.")] = "",
    pubkey: Annotated[
        Path | None, typer.Option(help="OpenSSH public key file provided by the partner.")
    ] = None,
    generate_key: Annotated[
        bool, typer.Option("--generate-key", help="Generate an ed25519 key pair locally.")
    ] = False,
    pattern: Annotated[
        list[str] | None,
        typer.Option("--pattern", help="Allowed file name glob (repeatable)."),
    ] = None,
    max_size: Annotated[int, typer.Option(help="Maximum file size in bytes.")] = DEFAULT_MAX_SIZE,
    schema: Annotated[
        str, typer.Option(help=f"Content schema: {', '.join(KNOWN_SCHEMAS)}.")
    ] = KNOWN_SCHEMAS[0],
    if_not_exists: Annotated[
        bool, typer.Option("--if-not-exists", help="Succeed (and reconcile) if it already exists.")
    ] = False,
) -> None:
    """Onboard a partner: registry record, S3 prefix and key-only SFTP user."""
    settings = Settings.from_env()
    public_key, private_path, private_bytes = _resolve_public_key(
        settings, name, pubkey, generate_key
    )
    if private_path and private_path.exists():
        _fail(f"{private_path} already exists; use --pubkey {private_path}.pub or rotate-key")

    spec = PartnerSpec(
        partner_id=name,
        display_name=display_name,
        public_key=public_key,
        allowed_patterns=tuple(pattern or DEFAULT_PATTERNS),
        max_file_size_bytes=max_size,
        schema=schema,
    )
    try:
        result = build_service(settings).create(spec, if_not_exists=if_not_exists)
    except (PartnerError, SftpGoError, ValueError) as exc:
        _fail(str(exc))
        return

    if private_path and private_bytes:
        write_private_key(private_path, private_bytes)
        write_public_key(private_path.with_name("id_ed25519.pub"), public_key)
        console.print(f"private key written to {private_path} (mode 600, never printed)")
    state = "created" if result.created else "already existed, reconciled"
    console.print(f"partner [bold]{name}[/bold] {state}; key {result.fingerprint}")
    console.print(f"SFTP user {result.sftpgo}: sftp -P 2022 {name}@localhost")


@partner_app.command("rotate-key")
def rotate_key(
    name: Annotated[str, typer.Option("--name", help="Partner id.")],
    pubkey: Annotated[Path | None, typer.Option(help="New OpenSSH public key file.")] = None,
    generate_key: Annotated[
        bool, typer.Option("--generate-key", help="Generate a new ed25519 key pair locally.")
    ] = False,
) -> None:
    """Replace a partner's key; the old key is refused immediately."""
    settings = Settings.from_env()
    public_key, private_path, private_bytes = _resolve_public_key(
        settings, name, pubkey, generate_key
    )
    staged: Path | None = None
    if private_path and private_bytes:
        # Stage the new key first, so a failure never leaves the partner keyless.
        staged = private_path.with_name("id_ed25519.new")
        write_private_key(staged, private_bytes, overwrite=True)
    try:
        new_fingerprint = build_service(settings).rotate_key(name, public_key)
    except (PartnerError, SftpGoError, ValueError) as exc:
        if staged:
            staged.unlink(missing_ok=True)
        _fail(str(exc))
        return
    if staged and private_path:
        staged.replace(private_path)  # atomic; the old private key is gone
        write_public_key(private_path.with_name("id_ed25519.pub"), public_key)
        console.print(f"new private key written to {private_path}")
    console.print(f"partner [bold]{name}[/bold] now uses key {new_fingerprint}")


@partner_app.command("disable")
def disable(name: Annotated[str, typer.Option("--name", help="Partner id.")]) -> None:
    """Block SFTP logins and make Validate reject new files."""
    _set_status(name, STATUS_DISABLED)


@partner_app.command("enable")
def enable(name: Annotated[str, typer.Option("--name", help="Partner id.")]) -> None:
    """Re-enable a disabled partner."""
    _set_status(name, STATUS_ACTIVE)


def _set_status(name: str, status: str) -> None:
    try:
        build_service(Settings.from_env()).set_status(name, status)
    except (PartnerError, SftpGoError) as exc:
        _fail(str(exc))
        return
    console.print(f"partner [bold]{name}[/bold] is now {status}")


@partner_app.command("list")
def list_partners() -> None:
    """Show all partners."""
    try:
        partners = build_service(Settings.from_env()).list()
    except (PartnerError, SftpGoError) as exc:
        _fail(str(exc))
        return
    table = Table("partner", "name", "status", "patterns", "max size", "schema", "key")
    for item in partners:
        table.add_row(
            item["partner_id"],
            item.get("name", ""),
            item.get("status", ""),
            ", ".join(item.get("allowed_patterns", [])),
            str(item.get("max_file_size_bytes", "")),
            item.get("schema", ""),
            item.get("key_fingerprint", ""),
        )
    console.print(table)


def main() -> None:
    app()

"""SSH key handling. Private keys are written to disk with mode 0600 and never printed."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

MIN_RSA_BITS = 3072


class InvalidPublicKeyError(ValueError):
    pass


def generate_keypair() -> tuple[bytes, str]:
    """Return (OpenSSH private key bytes, "ssh-ed25519 AAAA..." public key)."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    public = private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    return private_bytes, public.decode("ascii")


def normalize_public_key(text: str) -> str:
    """Validate an OpenSSH public key and return "<type> <base64>" (comment dropped)."""
    parts = text.strip().split()
    if len(parts) < 2:
        raise InvalidPublicKeyError("expected '<type> <base64> [comment]'")
    key_type, blob = parts[0], parts[1]
    try:
        key = serialization.load_ssh_public_key(f"{key_type} {blob}".encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise InvalidPublicKeyError(f"not a valid OpenSSH public key: {exc}") from exc
    if isinstance(key, rsa.RSAPublicKey) and key.key_size < MIN_RSA_BITS:
        raise InvalidPublicKeyError(f"RSA keys must have at least {MIN_RSA_BITS} bits")
    if not isinstance(key, ed25519.Ed25519PublicKey | ec.EllipticCurvePublicKey | rsa.RSAPublicKey):
        raise InvalidPublicKeyError(f"unsupported key type {key_type}")
    return f"{key_type} {blob}"


def fingerprint(public_key: str) -> str:
    """SHA256 fingerprint, formatted like `ssh-keygen -l`: SHA256:<base64, no padding>."""
    blob = base64.b64decode(public_key.split()[1])
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii")
    return f"SHA256:{digest.rstrip('=')}"


def write_private_key(path: Path, data: bytes, *, overwrite: bool = False) -> None:
    """Write a private key with mode 0600. Refuses to overwrite unless asked."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def write_public_key(path: Path, public_key: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(public_key + "\n", encoding="ascii")

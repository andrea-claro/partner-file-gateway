"""'Simulate a partner upload': a real SFTP upload, as the demo partner.

The file goes through SFTPGo -> S3 -> EventBridge -> Step Functions like any
partner file, so what the visitor sees in the dashboard is the real pipeline.
"""

from __future__ import annotations

import io
import random
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import paramiko


@dataclass(frozen=True)
class Sample:
    path: Path
    expected: str  # DELIVERED or REJECTED


@dataclass(frozen=True)
class SimulationResult:
    remote_name: str
    sample: str
    expected: str


class Uploader(Protocol):
    def upload(self, remote_name: str, data: bytes) -> None: ...


def list_samples(samples_dir: Path) -> list[Sample]:
    samples = [
        Sample(p, "DELIVERED") for p in sorted((samples_dir / "valid").glob("*")) if p.is_file()
    ]
    samples += [
        Sample(p, "REJECTED") for p in sorted((samples_dir / "invalid").glob("*")) if p.is_file()
    ]
    return samples


def remote_name_for(path: Path, now: datetime) -> str:
    """orders_basic.csv -> orders_basic_20261115T210405_3f9a.csv (keeps the pattern match)."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{path.stem}_{stamp}_{secrets.token_hex(2)}{path.suffix}"


class SftpUploader:
    def __init__(self, host: str, port: int, username: str, key_path: Path, known_hosts: Path):
        self.host = host
        self.port = port
        self.username = username
        self.key_path = key_path
        self.known_hosts = known_hosts

    def upload(self, remote_name: str, data: bytes) -> None:
        client = paramiko.SSHClient()
        client.load_host_keys(str(self.known_hosts))  # pinned by `make up`
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                pkey=paramiko.Ed25519Key.from_private_key_file(str(self.key_path)),
                allow_agent=False,
                look_for_keys=False,
                timeout=10,
            )
            with client.open_sftp() as sftp:
                sftp.putfo(io.BytesIO(data), remote_name)
        finally:
            client.close()


class Simulator:
    def __init__(
        self,
        samples: list[Sample],
        uploader: Uploader,
        rng: random.Random | None = None,
        valid_ratio: float = 0.7,
    ) -> None:
        if not samples:
            raise ValueError("no sample files found")
        self.valid = [s for s in samples if s.expected == "DELIVERED"]
        self.invalid = [s for s in samples if s.expected == "REJECTED"]
        self.uploader = uploader
        self.rng = rng or random.SystemRandom()
        self.valid_ratio = valid_ratio

    def run(self, now: datetime | None = None) -> SimulationResult:
        pool = (
            self.valid
            if (self.rng.random() < self.valid_ratio or not self.invalid)
            else self.invalid
        )
        sample = self.rng.choice(pool or self.invalid)
        remote_name = remote_name_for(sample.path, now or datetime.now(UTC))
        self.uploader.upload(remote_name, sample.path.read_bytes())
        return SimulationResult(
            remote_name=remote_name, sample=sample.path.name, expected=sample.expected
        )

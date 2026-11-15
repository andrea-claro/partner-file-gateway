from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    transfers_table: str = "transfers"
    partners_table: str = "partners"
    sftp_host: str = "sftpgo"
    sftp_port: int = 2022
    simulator_partner: str = "demo"
    simulator_key: Path = Path("/run/pfg/simulator/id_ed25519")
    known_hosts: Path = Path("/run/pfg/sftp/known_hosts")
    samples_dir: Path = _PACKAGE_ROOT.parent / "samples"
    simulate_per_ip_per_minute: int = 3
    simulate_global_per_minute: int = 30

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        d = cls()
        return cls(
            transfers_table=env.get("PFG_TRANSFERS_TABLE", d.transfers_table),
            partners_table=env.get("PFG_PARTNERS_TABLE", d.partners_table),
            sftp_host=env.get("PFG_SFTP_HOST", d.sftp_host),
            sftp_port=int(env.get("PFG_SFTP_PORT", d.sftp_port)),
            simulator_partner=env.get("PFG_SIMULATOR_PARTNER", d.simulator_partner),
            simulator_key=Path(env.get("PFG_SIMULATOR_KEY", str(d.simulator_key))),
            known_hosts=Path(env.get("PFG_KNOWN_HOSTS", str(d.known_hosts))),
            samples_dir=Path(env.get("PFG_SAMPLES_DIR", str(d.samples_dir))),
            simulate_per_ip_per_minute=int(
                env.get("PFG_SIMULATE_PER_IP_PER_MINUTE", d.simulate_per_ip_per_minute)
            ),
            simulate_global_per_minute=int(
                env.get("PFG_SIMULATE_GLOBAL_PER_MINUTE", d.simulate_global_per_minute)
            ),
        )

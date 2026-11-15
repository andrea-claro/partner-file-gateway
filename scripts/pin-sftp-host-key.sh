#!/bin/sh
# Pin the SFTP server's host key so every client (pfg, dashboard simulator,
# e2e tests, your own sftp) verifies it instead of trusting on every connect.
#
# Runs inside the tools container, on the private compose network, right after
# `make up`. SFTPGo keeps its host keys in its data volume, so the pin stays
# valid across container restarts. Output: .secrets/sftpgo/known_hosts
set -eu
cd "$(dirname "$0")/.."

host="${PFG_SFTP_HOST:-sftpgo}"
port="${PFG_SFTP_PORT:-2022}"
out=.secrets/sftpgo/known_hosts

mkdir -p "$(dirname "$out")"
keys="$(ssh-keyscan -T 10 -p "$port" -t ed25519 "$host" 2>/dev/null | grep -v '^#' | cut -d' ' -f2-)"
if [ -z "$keys" ]; then
  echo "error: could not read the SFTP host key from $host:$port" >&2
  exit 1
fi

tmp="$(mktemp)"
for name in "$host" localhost 127.0.0.1; do
  printf '[%s]:%s %s\n' "$name" "$port" "$keys" >> "$tmp"
done

if [ -f "$out" ] && ! cmp -s "$tmp" "$out"; then
  echo "warning: the SFTP host key changed (was the sftpgo-data volume recreated?)." >&2
fi
mv "$tmp" "$out"
chmod 644 "$out"
echo "pinned SFTP host key in $out"

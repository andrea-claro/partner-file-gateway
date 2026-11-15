#!/bin/sh
# Onboard the demo partner used by the e2e tests and the dashboard simulator.
# Idempotent: re-running after a LocalStack restart restores the registry
# record and reuses the existing key.
set -eu
cd "$(dirname "$0")/.."

key=.secrets/partners/demo/id_ed25519
if [ -f "$key" ]; then
  key_args="--pubkey $key.pub"
else
  key_args="--generate-key"
fi

# shellcheck disable=SC2086 # key_args is intentionally split
python -m pfg partner create \
  --name demo \
  --display-name "Demo Partner" \
  --pattern 'orders_*.csv' \
  --pattern 'orders_*.json' \
  --if-not-exists \
  $key_args

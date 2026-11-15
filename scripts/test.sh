#!/bin/sh
# `make test`: lint + unit tests. Unit tests use moto and never touch the network.
set -eu
cd "$(dirname "$0")/.."

./scripts/lint.sh
echo "==> pytest (unit)"
pytest -p no:cacheprovider tests/unit "$@"

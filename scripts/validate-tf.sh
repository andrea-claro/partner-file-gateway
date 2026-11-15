#!/bin/sh
# terraform validate for both targets. infra/envs/aws is validate-only:
# nothing in this repository ever runs plan or apply against it.
set -eu
cd "$(dirname "$0")/.."

for env in local aws; do
  echo "==> infra/envs/$env"
  terraform -chdir="infra/envs/$env" init -backend=false -input=false >/dev/null
  terraform -chdir="infra/envs/$env" validate
done

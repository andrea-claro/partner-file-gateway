#!/bin/sh
# Terraform on infra/envs/local. Every provider endpoint points at LocalStack.
set -eu
cd "$(dirname "$0")/.."

action="${1:-plan}"
dir=infra/envs/local

case "${TF_VAR_localstack_endpoint:-}" in
  http://localstack:4566 | http://localhost:4566 | http://127.0.0.1:4566) ;;
  *)
    echo "error: TF_VAR_localstack_endpoint must point at LocalStack (got '${TF_VAR_localstack_endpoint:-}')." >&2
    exit 1
    ;;
esac

terraform -chdir="$dir" init -input=false >/dev/null

case "$action" in
  plan) terraform -chdir="$dir" plan -input=false ;;
  apply) terraform -chdir="$dir" apply -input=false -auto-approve ;;
  destroy) terraform -chdir="$dir" destroy -input=false -auto-approve ;;
  output) terraform -chdir="$dir" output ;;
  *)
    echo "usage: $0 plan|apply|destroy|output" >&2
    exit 2
    ;;
esac

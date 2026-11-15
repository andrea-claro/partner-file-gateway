#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

echo "==> ruff"
ruff check .
ruff format --check .

echo "==> terraform fmt"
terraform fmt -check -recursive infra

echo "==> tflint"
tflint --init >/dev/null
tflint --recursive --config "$(pwd)/.tflint.hcl"

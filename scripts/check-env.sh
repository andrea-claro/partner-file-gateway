#!/bin/sh
# Fail fast, with a helpful message, when local configuration is missing.
set -eu
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "error: .env is missing. Run 'make secrets' first." >&2
  exit 1
fi

value_of() {
  grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- || true
}

token="${LOCALSTACK_AUTH_TOKEN:-$(value_of LOCALSTACK_AUTH_TOKEN)}"
case "$token" in
  '' | '<'*)
    echo "error: LOCALSTACK_AUTH_TOKEN is not set." >&2
    echo "       Create a free Hobby account at https://app.localstack.cloud," >&2
    echo "       copy your personal auth token and put it in .env." >&2
    exit 1
    ;;
esac

case "$(value_of SFTPGO_ADMIN_PASSWORD)" in
  '' | '<'*)
    echo "error: SFTPGO_ADMIN_PASSWORD is not set. Run 'make secrets'." >&2
    exit 1
    ;;
esac

if [ "${1:-}" = "--tunnel" ]; then
  case "${TUNNEL_TOKEN:-$(value_of TUNNEL_TOKEN)}" in
    '' | '<'*)
      echo "error: TUNNEL_TOKEN is not set in .env." >&2
      echo "       Only needed for the bundled cloudflared container. If a tunnel" >&2
      echo "       already runs on this machine, route it to http://localhost:\${DASHBOARD_PORT:-8000}." >&2
      exit 1
      ;;
  esac
fi

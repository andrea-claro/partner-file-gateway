#!/bin/sh
# Create local-only configuration and secrets. Safe to re-run.
#
# - .env is created from .env.example (mode 600) and every "<generated>" value
#   is replaced with a random secret.
# - .secrets/ holds partner keys and the pinned SFTP host key (written later by
#   `pfg` and scripts/pin-sftp-host-key.sh).
#
# Both paths are gitignored and blocked by scripts/git-hooks/pre-commit.
set -eu
cd "$(dirname "$0")/.."
umask 077

ENV_FILE=.env

if [ ! -f "$ENV_FILE" ]; then
  cp .env.example "$ENV_FILE"
  echo "created $ENV_FILE from .env.example"
fi
chmod 600 "$ENV_FILE"

# Add variables that exist in .env.example but are missing from .env (for an
# .env written by hand, or after new variables were added). Existing values are
# never touched.
added=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    '' | '#'*) continue ;;
  esac
  key="${line%%=*}"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    [ -n "$(tail -c 1 "$ENV_FILE")" ] && printf '\n' >> "$ENV_FILE"
    printf '%s\n' "$line" >> "$ENV_FILE"
    added="$added $key"
  fi
done < .env.example
[ -n "$added" ] && echo "added missing variables to $ENV_FILE:$added"

random_secret() {
  openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-32
}

if grep -q '=<generated>$' "$ENV_FILE"; then
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      *'=<generated>') printf '%s=%s\n' "${line%%=*}" "$(random_secret)" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "generated local secrets in $ENV_FILE"
fi

# Directories are created up front so Docker never creates them as root-owned
# bind-mount targets.
mkdir -p .secrets/partners/demo .secrets/sftpgo
chmod 700 .secrets
echo "local secrets ready (.env and .secrets/ are gitignored)"

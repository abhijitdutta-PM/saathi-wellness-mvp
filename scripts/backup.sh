#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then echo "Missing .env; copy .env.example and configure credentials first." >&2; exit 1; fi
set -a
. ./.env
set +a
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file="backups/saathi-${stamp}.dump"
# Use the database administrator for complete backups because forced RLS intentionally restricts the app role.
# Protect this file as highly sensitive: it contains student records and secrets are not embedded in the dump.
docker compose exec -T -e PGPASSWORD="${POSTGRES_ADMIN_PASSWORD}" db pg_dump -U postgres -d wellness -Fc > "$file"
chmod 600 "$file"
printf 'Created backup artifact (not encrypted by this script): %s\n' "$file"
printf 'IMPORTANT: move it to approved encrypted off-host storage and test restoration regularly.\n'

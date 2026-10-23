#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ $# -ne 1 ]; then echo "Usage: scripts/restore.sh backups/saathi-YYYYMMDDTHHMMSSZ.dump" >&2; exit 2; fi
file="$1"
if [ ! -f "$file" ]; then echo "Backup file not found: $file" >&2; exit 2; fi
printf 'WARNING: this destructive operation replaces objects in the target database. Use a recovery environment first.\n'
printf 'Type RESTORE to continue: '
read confirm
[ "$confirm" = "RESTORE" ] || { echo "Cancelled."; exit 1; }
set -a
. ./.env
set +a
# Prefer restoring into a new recovery database and validating it before swapping production traffic.
docker compose exec -T -e PGPASSWORD="${POSTGRES_ADMIN_PASSWORD}" db pg_restore -U postgres -d wellness --clean --if-exists < "$file"
printf 'Restore command completed. Validate data, application startup, RLS, and backups before reopening access.\n'

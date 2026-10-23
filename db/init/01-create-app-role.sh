#!/bin/sh
set -eu
: "${WELLNESS_DB_PASSWORD:?WELLNESS_DB_PASSWORD must be provided}"
# The local development password should not contain a single quote. For production, provision
# credentials using your secrets manager and replace this bootstrap script.
case "$WELLNESS_DB_PASSWORD" in
  *"'"*) echo "WELLNESS_DB_PASSWORD may not contain a single quote for this bootstrap script" >&2; exit 1 ;;
esac
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE wellness_app LOGIN PASSWORD '${WELLNESS_DB_PASSWORD}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO wellness_app;
GRANT USAGE, CREATE ON SCHEMA public TO wellness_app;
ALTER ROLE wellness_app SET statement_timeout = '15s';
EOSQL

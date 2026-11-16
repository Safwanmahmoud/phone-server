#!/data/data/com.termux/files/usr/bin/bash
# Installs PostgreSQL and runs it under PM2 as ps-postgres. Safe to run again.
# Then give an app its own database with:
#   cd ~/phone-server && .venv/bin/python -m server.cli create-db <app>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${PS_DATA:-$HOME/.phone-server}"
PGDATA="$DATA/postgres"
cd "$ROOT"

echo "→ Package"
dpkg -s postgresql >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive pkg install -y postgresql </dev/null

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  echo "→ Creating the database cluster in $PGDATA"
  # Superuser "postgres", trusted only over the local socket; TCP needs a password.
  initdb -D "$PGDATA" -U postgres -E UTF8 --locale=C \
    --auth-local=trust --auth-host=scram-sha-256 >/dev/null
  cat >> "$PGDATA/postgresql.conf" <<'EOF'

# --- phone-server ---
# Only reachable from the phone itself.
listen_addresses = '127.0.0.1'
port = 5432
# Small footprint. Android kills background processes once there are more than
# 32 across all apps, so keep Postgres's helper processes to a minimum.
shared_buffers = 32MB
max_connections = 30
wal_level = minimal
max_wal_senders = 0
max_worker_processes = 2
max_parallel_workers = 0
max_parallel_workers_per_gather = 0
max_logical_replication_workers = 0
max_sync_workers_per_subscription = 0
EOF
fi

echo "→ Service"
pm2 startOrRestart postgres.config.js >/dev/null
pm2 save --force >/dev/null

for _ in $(seq 1 30); do
  pg_isready -h 127.0.0.1 -p 5432 -q && break
  sleep 1
done
pg_isready -h 127.0.0.1 -p 5432

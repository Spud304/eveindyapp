#!/usr/bin/env bash
# Back up the dev database (the real account's data and ESI tokens) together with
# backend/.env, which holds the key the tokens are encrypted with: a dump without the key
# cannot decrypt them, and the key without the dump has nothing to decrypt.
#
#   deploy/backup-dev.sh              # into ~/eveindy-backups
#   BACKUP_DIR=/mnt/g/backups deploy/backup-dev.sh
#
# Restore: gunzip -c <dump> | docker compose -f deploy/docker-compose.dev.yml exec -T db \
#   psql -U eveindy -d eveindy   (into an empty database), and put the .env copy back.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
dir="${BACKUP_DIR:-$HOME/eveindy-backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$dir"

docker compose -f "$root/deploy/docker-compose.dev.yml" exec -T db \
  pg_dump -U eveindy -d eveindy --no-owner | gzip > "$dir/eveindy-$stamp.sql.gz"
cp "$root/backend/.env" "$dir/backend-$stamp.env"

echo "wrote $dir/eveindy-$stamp.sql.gz and $dir/backend-$stamp.env"

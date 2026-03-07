#!/bin/bash
set -e

# 1. Ensure local DB is stamped so autogenerate can diff against it
flask --app src.main:app db upgrade 2>&1 || flask --app src.main:app db stamp head

# 2. Check if models have changed and autogenerate a migration if needed
BEFORE=$(ls migrations/versions/*.py 2>/dev/null | wc -l)
flask --app src.main:app db migrate -m "auto" 2>&1 || true
AFTER=$(ls migrations/versions/*.py 2>/dev/null | wc -l)

if [ "$AFTER" -gt "$BEFORE" ]; then
    echo "New migration generated -- review before deploying."
    ls -t migrations/versions/*.py | head -1
else
    echo "No schema changes detected."
fi

# 3. Build and restart
docker compose build
docker compose up -d
docker compose logs -f

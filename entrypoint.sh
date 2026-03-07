#!/bin/sh
if ! flask --app src.main:app db upgrade 2>&1; then
    echo "Migration failed -- stamping DB to head (likely db.create_all() schema)"
    flask --app src.main:app db stamp head
fi
exec "$@"

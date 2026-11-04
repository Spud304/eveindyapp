#!/bin/sh
# web | worker | scheduler | any other command. Adapted from the AT Tool.
set -eu
cd /app

wait_for_db() {
  i=0
  check='import psycopg, os; psycopg.connect(os.environ["DATABASE_URL"]).close()'
  until python -c "$check" 2>/dev/null; do
    i=$((i+1))
    if [ $i -gt 60 ]; then
      echo "database not reachable; last error:"
      python -c "$check" 2>&1 | tail -3
      exit 1
    fi
    sleep 2
  done
}

case "${1:-web}" in
  web)
    wait_for_db
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    # Trust X-Forwarded-* only from the Docker networks (Caddy), as Caddy trusts private ranges.
    exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers \
      --forwarded-allow-ips="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    ;;
  worker)
    wait_for_db
    # On-demand syncs only ("refresh now", first sync after linking). No beat: cron owns the schedule.
    exec celery -A config worker --loglevel=INFO --concurrency=2
    ;;
  scheduler)
    wait_for_db
    # Full path: as PID 1 supercronic re-executes itself from argv[0], which fails for a bare name.
    exec /usr/local/bin/supercronic /app/deploy/crontab
    ;;
  *)
    exec "$@"
    ;;
esac

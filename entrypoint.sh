#!/bin/sh
flask --app src.main:app db upgrade
exec "$@"

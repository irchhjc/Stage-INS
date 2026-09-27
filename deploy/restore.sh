#!/bin/sh
set -eu

if [ "$#" -ne 3 ] || [ "$3" != "--confirm" ]; then
    echo "Usage : $0 POSTGRES.dump INSTANCE.tar.gz --confirm" >&2
    exit 1
fi

DATABASE_DUMP=$(realpath "$1")
INSTANCE_ARCHIVE=$(realpath "$2")
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

COMPOSE="docker compose --env-file .env.production -f compose.prod.yaml"

$COMPOSE stop caddy web
$COMPOSE up -d db
$COMPOSE exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
$COMPOSE exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' < "$DATABASE_DUMP"

docker run --rm -v dsf_instance_data:/target alpine:3.23 sh -c 'rm -rf /target/* /target/.[!.]* /target/..?* 2>/dev/null || true'
docker run --rm \
    -v dsf_instance_data:/target \
    -v "$(dirname "$INSTANCE_ARCHIVE"):/backup:ro" \
    alpine:3.23 \
    sh -c "tar -C /target -xzf '/backup/$(basename "$INSTANCE_ARCHIVE")' && chown -R 10001:10001 /target"

$COMPOSE up -d
echo "Restauration terminée. Vérifiez /healthz et connectez-vous à l'application."

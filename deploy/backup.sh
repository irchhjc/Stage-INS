#!/bin/sh
set -eu
umask 077

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

if [ ! -f .env.production ]; then
    echo "Fichier .env.production absent." >&2
    exit 1
fi

BACKUP_DIR=${BACKUP_DIR:-"$PROJECT_DIR/backups"}
RETENTION_DAYS=${RETENTION_DAYS:-14}
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
COMPOSE="docker compose --env-file .env.production -f compose.prod.yaml"

mkdir -p "$BACKUP_DIR"

$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' \
    > "$BACKUP_DIR/postgres_${TIMESTAMP}.dump"

docker run --rm \
    -v dsf_instance_data:/source:ro \
    -v "$BACKUP_DIR:/backup" \
    alpine:3.23 \
    tar -C /source -czf "/backup/instance_${TIMESTAMP}.tar.gz" .

find "$BACKUP_DIR" -type f \( -name 'postgres_*.dump' -o -name 'instance_*.tar.gz' \) \
    -mtime "+$RETENTION_DAYS" -delete

echo "Sauvegarde créée :"
echo "- $BACKUP_DIR/postgres_${TIMESTAMP}.dump"
echo "- $BACKUP_DIR/instance_${TIMESTAMP}.tar.gz"

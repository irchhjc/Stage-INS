#!/bin/sh
set -eu
umask 077

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

if [ ! -f .env.production ]; then
    echo "Fichier .env.production absent sur le VPS." >&2
    exit 1
fi

LOCK_DIR=/tmp/dsf-control-deploy.lock
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "Un autre deploiement est deja en cours." >&2
    exit 1
fi
trap 'rmdir "$LOCK_DIR"' EXIT INT TERM

COMPOSE="docker compose --env-file .env.production -f compose.prod.yaml"
$COMPOSE config --quiet

if $COMPOSE ps --services --status running | grep -qx db; then
    echo "Sauvegarde pre-deploiement..."
    ./deploy/backup.sh
else
    echo "Base non demarree : sauvegarde pre-deploiement ignoree."
fi

./deploy/deploy.sh

$COMPOSE exec -T web python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5)" \
    >/dev/null

echo "Deploiement CI/CD valide."

#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"

if [ ! -f .env.production ]; then
    echo "Fichier .env.production absent. Copiez .env.production.example puis remplacez tous les secrets." >&2
    exit 1
fi

COMPOSE="docker compose --env-file .env.production -f compose.prod.yaml"

$COMPOSE config --quiet
$COMPOSE pull db caddy
$COMPOSE build --pull web
$COMPOSE up -d --remove-orphans

attempt=1
while [ "$attempt" -le 40 ]; do
    if $COMPOSE exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5)" >/dev/null 2>&1; then
        echo "Déploiement terminé : l'application et PostgreSQL répondent correctement."
        $COMPOSE ps
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 3
done

echo "Le healthcheck n'est pas devenu disponible. Consultez les journaux :" >&2
echo "$COMPOSE logs --tail=200 web db caddy" >&2
exit 1

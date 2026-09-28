# Déploiement du contrôle DSF sur le VPS Hostinger

Cette configuration lance quatre composants isolés :

- `caddy` expose les ports 80/443 et gère le HTTPS dès qu'un domaine pointe vers le VPS ;
- `web` exécute Flask avec Gunicorn, sans privilèges root ;
- `db` exécute PostgreSQL 18 sans publier son port sur Internet ;
- des volumes Docker conservent PostgreSQL, les classeurs importés, les exports et les certificats.

## 1. Préparer le VPS

Connectez-vous avec une clé SSH :

```bash
ssh root@92.113.26.206
```

Vérifiez Docker et Compose :

```bash
docker --version
docker compose version
```

Dans le pare-feu Hostinger et dans UFW, ouvrez uniquement SSH, HTTP et HTTPS :

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Ne publiez jamais le port PostgreSQL `5432`.

## 2. Installer le projet

Placez le dépôt dans `/opt/dsf-control`, puis créez la configuration privée :

```bash
cd /opt
git clone VOTRE_URL_GIT dsf-control
cd dsf-control
cp .env.production.example .env.production
chmod 600 .env.production
chmod +x deploy/*.sh
```

Générez deux secrets différents :

```bash
openssl rand -hex 32
openssl rand -base64 36 | tr -dc 'A-Za-z0-9' | head -c 32; echo
```

Éditez `.env.production` et remplacez impérativement :

- `POSTGRES_PASSWORD` ;
- `SECRET_KEY` ;
- `INITIAL_ADMIN_PASSWORD`.

Utilisez uniquement des lettres et chiffres pour `POSTGRES_PASSWORD`. Aucun secret ne doit être ajouté à Git.

Cette instance utilise le domaine public `dsf-compta-inscg.tech`. Vérifiez d'abord
que son enregistrement DNS `A` pointe vers l'adresse du VPS :

```bash
getent ahostsv4 dsf-compta-inscg.tech
```

La sortie doit contenir `92.113.26.206`. Configurez ensuite :

```text
SITE_ADDRESS=dsf-compta-inscg.tech
SESSION_COOKIE_SECURE=true
```

L'accès direct `http://92.113.26.206` ne doit servir qu'au diagnostic temporaire :
il ne chiffre ni les identifiants ni les cookies de session.

N'utilisez pas le nom d'hôte technique `srv2013685.hstgr.cloud` comme adresse HTTPS
publique : Caddy sert le certificat du domaine configuré dans `SITE_ADDRESS`.

## 3. Démarrer et vérifier

```bash
./deploy/deploy.sh
docker compose --env-file .env.production -f compose.prod.yaml ps
docker compose --env-file .env.production -f compose.prod.yaml logs --tail=200 web db caddy
```

Vérifiez ensuite :

```bash
curl -f https://dsf-compta-inscg.tech/healthz
```

Le résultat attendu est `{"status":"ok"}`. Ouvrez ensuite
`https://dsf-compta-inscg.tech`.

## 4. Migrer la base et les classeurs Windows existants

Sur le poste Windows, dans le dossier du projet :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\create_vps_migration_bundle.ps1
```

Le script crée `migration_bundle_AAAAMMJJ_HHMMSS` avec `postgres.dump` et `instance.tar.gz`. Copiez ces deux fichiers vers le VPS :

```powershell
scp .\migration_bundle_AAAAMMJJ_HHMMSS\* root@92.113.26.206:/opt/dsf-control/backups/
```

Sur le VPS, restaurez les deux éléments :

```bash
cd /opt/dsf-control
./deploy/restore.sh backups/postgres.dump backups/instance.tar.gz --confirm
docker compose --env-file .env.production -f compose.prod.yaml exec -T web \
  python -m app.maintenance.relink_import_files
docker compose --env-file .env.production -f compose.prod.yaml exec -T web \
  python -m app.maintenance.relink_import_files --apply
```

La première commande de reliaison est un aperçu. La seconde enregistre les chemins Linux seulement si tous les classeurs originaux sont présents.

## 5. Sauvegardes quotidiennes

Testez d'abord :

```bash
./deploy/backup.sh
```

Puis ajoutez une tâche quotidienne avec `crontab -e` :

```cron
0 2 * * * cd /opt/dsf-control && ./deploy/backup.sh >> /var/log/dsf-backup.log 2>&1
```

Le script conserve 14 jours par défaut. Copiez régulièrement les sauvegardes vers un autre serveur ou un stockage objet : une sauvegarde conservée uniquement sur le VPS ne protège pas contre la perte du serveur.

## 6. Mettre à jour l'application

```bash
cd /opt/dsf-control
git pull --ff-only
./deploy/deploy.sh
```

Pour diagnostiquer une erreur :

```bash
docker compose --env-file .env.production -f compose.prod.yaml ps
docker compose --env-file .env.production -f compose.prod.yaml logs --tail=300 web db caddy
```

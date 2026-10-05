# Connexions PostgreSQL

Le serveur local traite huit requêtes simultanées avec Waitress. Le pool
conserve au maximum huit connexions par processus (`DB_POOL_SIZE=8`,
`max_overflow=0`). Il attend au maximum dix secondes une connexion libre
(`DB_POOL_TIMEOUT=10`). Ces variables sont facultatives et doivent être des
entiers strictement positifs. Plusieurs utilisateurs partagent ce pool :
huit connexions ne signifient pas huit comptes autorisés.

Le contrôle `pool_pre_ping` remplace une connexion périmée avant son utilisation.
Une coupure reconnue pendant la lecture initiale de l'utilisateur déclenche
une seule nouvelle tentative après nettoyage de la session SQLAlchemy.
Les opérations métier et les écritures ne sont jamais rejouées automatiquement.
Après une erreur, vérifier la dernière saisie avant de la répéter.

Les erreurs sont enregistrées dans `instance/logs/database-<processus>.log`
avec rotation à 1 Mo et deux archives par processus. Les fichiers des anciens
processus restent présents. Les journaux ne contiennent ni mot de passe ni
valeurs SQL. Ils distinguent :

- `database_pool_busy` : attente dépassée dans le pool de l'application ;
- `database_connection_limit` : PostgreSQL refuse des connexions supplémentaires ;
- `database_access_denied` : Windows refuse l'accès réseau (10013) ;
- `database_unavailable` : autre erreur de disponibilité.

Le code Windows 10013 ne peut pas être réparé par un agrandissement du pool.
Si plusieurs processus sont lancés, leurs limites de connexions s'additionnent.
Après toute modification de configuration, relancer le serveur.

Validation du 21 septembre 2026 : 32 lectures PostgreSQL avec 16 clients de test,
pic de huit connexions, zéro connexion empruntée en fin de test et récupération
d'une connexion de test fermée. Ce test ne mesure pas la capacité maximale de
l'application et ne simule pas des écritures concurrentes.

Référence : https://docs.sqlalchemy.org/en/20/core/pooling.html

## Consulter la base du VPS avec pgAdmin (tunnel SSH)

PostgreSQL n'écoute sur le VPS que sur `127.0.0.1:5432` (voir `compose.prod.yaml`).
Il n'est jamais joignable depuis Internet : on passe par un tunnel SSH.
Ne retirez jamais le `127.0.0.1` devant le port et n'ouvrez pas 5432 dans le pare-feu.

1. **Déployer la configuration** : après le push sur `main`, la pipeline recrée le conteneur
   `db` avec le port local. Vérifier sur le VPS : `ss -ltn | grep 5432` doit afficher
   `127.0.0.1:5432` (et non `0.0.0.0:5432`).
2. **Identifiants** (sur le VPS) : `grep -E "^POSTGRES_(DB|USER|PASSWORD)=" /opt/dsf-control/.env.production`
   (base `insdsf`, utilisateur `dsf_app` par défaut).
3. **Ouvrir le tunnel** depuis Windows : `.\scripts\open_db_tunnel.ps1`
   (ou `ssh -N -L 5433:127.0.0.1:5432 root@92.113.26.206`). Laisser la fenêtre ouverte.
4. **pgAdmin** : clic droit sur *Servers* > *Register* > *Server…*
   - General : Name = `INS DSF (VPS)`
   - Connection : Host = `localhost`, Port = `5433`, Maintenance database = `insdsf`,
     Username = `dsf_app`, Password = celui de `.env.production`
   - Save.
5. **Arborescence** : `INS DSF (VPS) > Databases > insdsf > Schemas > public > Tables`.

Bonnes pratiques : lire avec `SELECT`, ne pas modifier les données à la main (le journal
d'audit et les contrôles de l'application seraient contournés), lancer `./deploy/backup.sh`
avant toute intervention, fermer le tunnel (Ctrl+C) en fin de session.

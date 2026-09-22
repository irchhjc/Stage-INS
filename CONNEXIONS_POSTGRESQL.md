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

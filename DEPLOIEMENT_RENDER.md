# Render : multi-utilisateur et sessions persistantes

## Architecture de production

- PostgreSQL stocke les comptes, affectations, corrections, validations et journaux.
- Le disque persistant conserve les classeurs Excel originaux et les exports.
- La session Flask reste dans un cookie signé du navigateur.
- `SECRET_KEY` doit rester strictement identique entre tous les redémarrages et déploiements.

SQLite reste adapté au développement local, mais ne doit pas servir plusieurs contrôleurs simultanément en production.

Le Blueprint utilise le plus petit plan PostgreSQL payant (`0.1c-256mb`). Une base PostgreSQL gratuite Render expire après 30 jours et n'offre pas de sauvegarde gérée : elle ne répond donc pas à l'exigence de conservation durable.

## Variables du service Web

Dans **Environment**, définir :

```text
DATABASE_URL=<Internal Database URL de Render PostgreSQL>
SECRET_KEY=<valeur aléatoire longue, créée une seule fois et jamais remplacée>
SESSION_LIFETIME_HOURS=168
SESSION_COOKIE_SECURE=true
```

La connexion reste alors valide pendant sept jours d'activité et sa date d'expiration est renouvelée à chaque requête. Un redémarrage de l'application ne détruit pas la session tant que `SECRET_KEY` reste inchangée.

## Commande de démarrage

```text
gunicorn run:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 300
```

## Migration importante

Ne pas remplacer directement l'ancienne `DATABASE_URL` SQLite si les données actuelles doivent être conservées : PostgreSQL démarrerait vide. Sauvegarder la base SQLite et les classeurs originaux, migrer les tables, contrôler les totaux, puis seulement basculer le service.

Le fichier `render.yaml` configure automatiquement cette architecture pour un nouveau Blueprint. Pour le service existant `dsf-compta`, créer PostgreSQL puis recopier manuellement son **Internal Database URL** dans `DATABASE_URL`.

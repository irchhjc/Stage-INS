# Serveur DSF local sous Windows

Cette installation permet à plusieurs contrôleurs d'utiliser l'application sans accès Internet, à condition que leurs ordinateurs soient connectés au même réseau Wi-Fi ou Ethernet que l'ordinateur serveur.

## Architecture retenue

- votre ordinateur héberge Flask avec Waitress ;
- PostgreSQL conserve les utilisateurs, affectations et contrôles ;
- les contrôleurs ouvrent une adresse locale telle que `http://192.168.1.20:8080` ;
- Bootstrap est inclus dans l'application : l'interface n'appelle plus le CDN Internet.

Le lien Render et le lien local utilisent deux bases différentes. Ne les utilisez pas comme deux copies modifiables de la même base sans mécanisme de synchronisation.

## 1. Préparer l'ordinateur serveur

L'ordinateur doit rester allumé pendant le travail des contrôleurs. Branchez-le au secteur et désactivez la mise en veille automatique pendant les heures de contrôle. Utilisez de préférence une connexion Ethernet et attribuez une adresse IP fixe à l'ordinateur dans les réglages du routeur.

## 2. Installer et préparer PostgreSQL

Installez PostgreSQL pour Windows puis ouvrez **pgAdmin > Query Tool** avec le compte administrateur PostgreSQL. Exécutez séparément :

```sql
CREATE USER dsf_app WITH PASSWORD 'remplacez_par_un_mot_de_passe_long';
CREATE DATABASE dsf_control OWNER dsf_app;
```

Choisissez de préférence un mot de passe alphanumérique long. Si le mot de passe contient `@`, `:`, `/`, `#` ou `%`, ces caractères doivent être encodés dans l'URL de connexion.

L'URL locale aura cette forme :

```text
postgresql+psycopg://dsf_app:VOTRE_MOT_DE_PASSE@127.0.0.1:5432/dsf_control
```

## 3. Configurer l'application

Ouvrez PowerShell dans le dossier du projet puis exécutez :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\configure_local_server.ps1
```

Le script demande séparément, sans les afficher, le mot de passe PostgreSQL de `dsf_app` puis le mot de passe initial de l'administrateur de l'application. Il construit correctement l'URL, crée une clé de session aléatoire, installe les dépendances, teste PostgreSQL et initialise les tables. La configuration privée est enregistrée dans `.local-server.ps1`, fichier exclu de Git.

Ne relancez pas la configuration si ce fichier existe : utilisez simplement le script de démarrage. La configuration refuse par défaut d'écraser la clé existante, car son remplacement déconnecterait toutes les sessions. L'option `-Force` est réservée à une réinitialisation volontaire.

## 4. Autoriser uniquement le réseau privé Windows

Ouvrez PowerShell **en tant qu'administrateur** et exécutez une seule fois :

```powershell
New-NetFirewallRule -DisplayName "DSF local - port 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
```

Vérifiez que le réseau Windows est classé comme **Privé**, jamais Public pour cette règle.

N'activez aucune redirection du port 8080 sur le routeur. Utilisez un Wi-Fi protégé par WPA2 ou WPA3 et limitez l'accès aux appareils de travail autorisés. Pour un réseau institutionnel partagé ou non maîtrisé, ajoutez ensuite HTTPS avec un certificat interne.

## 5. Démarrer le serveur

Dans PowerShell, depuis le projet :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start_local_server.ps1
```

Le script affiche le lien à communiquer, par exemple :

```text
http://192.168.1.20:8080
```

Les contrôleurs doivent être connectés au même réseau. Gardez la fenêtre PowerShell ouverte : `Ctrl+C` arrête le serveur.

## 6. Vérifier avant utilisation réelle

1. Ouvrez le lien local sur l'ordinateur serveur.
2. Connectez-vous comme administrateur.
3. Créez un compte contrôleur de test.
4. Depuis un deuxième ordinateur du même réseau, ouvrez le lien et connectez-vous.
5. Importez un petit classeur de test, affectez une DSF et vérifiez une cellule.
6. Redémarrez le serveur puis confirmez que l'utilisateur et la modification existent toujours.

## Sauvegardes indispensables

PostgreSQL conserve les données après l'arrêt de l'application ou de l'ordinateur, mais cela ne protège pas contre une panne de disque, un vol ou une suppression. Configurez une sauvegarde PostgreSQL quotidienne vers un support différent et conservez aussi le dossier `instance`, qui contient les fichiers Excel originaux et les exports.

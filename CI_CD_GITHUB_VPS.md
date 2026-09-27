# Pipeline CI/CD GitHub vers le VPS

La pipeline `.github/workflows/ci-cd.yml` applique cet ordre :

1. tests Python hors navigateur ;
2. test du parcours Playwright dans Chromium ;
3. construction de l'image Docker ;
4. deploiement uniquement sur un push de la branche `main` ;
5. sauvegarde PostgreSQL et du volume `instance` ;
6. reconstruction, redemarrage et verification de `/healthz`.

Un echec avant l'etape 4 empeche toute modification du VPS. La synchronisation
exclut `.env.production`, `backups/`, `instance/`, les archives et les fichiers
locaux sensibles.

## 1. Creer l'utilisateur de deploiement

Sur le VPS, en tant que `root` :

```bash
adduser --disabled-password --gecos "" dsfdeploy
usermod -aG docker dsfdeploy
chown -R dsfdeploy:dsfdeploy /opt/dsf-control
install -d -m 700 -o dsfdeploy -g dsfdeploy /home/dsfdeploy/.ssh
```

## 2. Creer une cle dediee

Sur le poste Windows, depuis le dossier du projet :

```powershell
New-Item -ItemType Directory -Force .ci-secrets | Out-Null
ssh-keygen -t ed25519 -a 100 -N "" -C "github-actions-dsf" -f .ci-secrets\github-actions-dsf-user
Get-Content .ci-secrets\github-actions-dsf-user.pub
```

Copier la cle publique affichee, puis sur le VPS :

```bash
printf '%s\n' 'COLLER_LA_CLE_PUBLIQUE_ICI' > /home/dsfdeploy/.ssh/authorized_keys
chown dsfdeploy:dsfdeploy /home/dsfdeploy/.ssh/authorized_keys
chmod 600 /home/dsfdeploy/.ssh/authorized_keys
```

Tester depuis Windows avant de continuer :

```powershell
ssh -i .ci-secrets\github-actions-dsf-user dsfdeploy@92.113.26.206 "docker version --format '{{.Server.Version}}'"
```

## 3. Creer l'environnement GitHub

Dans `github.com/irchhjc/Stage-INS` :

1. ouvrir `Settings` puis `Environments` ;
2. creer `production` ;
3. limiter le deploiement a la branche `main` ;
4. ajouter, si le forfait GitHub le permet, une approbation obligatoire.

Ajouter ces secrets a l'environnement `production` :

- `VPS_HOST` : `92.113.26.206` ;
- `VPS_USER` : `dsfdeploy` ;
- `VPS_SSH_PRIVATE_KEY` : contenu complet de `.ci-secrets/github-actions-dsf-user` ;
- `VPS_KNOWN_HOSTS` : ligne obtenue avec la commande suivante depuis Windows :

```powershell
ssh-keyscan -H 92.113.26.206
```

Comparer d'abord l'empreinte de cette ligne avec celle deja enregistree dans
`$HOME/.ssh/known_hosts`. Ne jamais utiliser `StrictHostKeyChecking=no` dans la
pipeline.

## 4. Declencher la pipeline

Apres avoir valide et pousse les fichiers sur `main`, GitHub lance
automatiquement la pipeline. Elle peut aussi etre lancee depuis l'onglet
`Actions` avec `Run workflow`.

Apres le premier succes, supprimer la cle privee locale :

```powershell
Remove-Item -LiteralPath .ci-secrets\github-actions-dsf-user -Force
```

Conserver la cle publique ne pose pas de probleme. Pour revoquer la pipeline,
supprimer sa ligne de `/home/dsfdeploy/.ssh/authorized_keys` et supprimer le
secret `VPS_SSH_PRIVATE_KEY` dans GitHub.

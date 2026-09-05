# Contrôle de conformité des DSF

Application Web Flask destinée au contrôle manuel, à la correction, à la validation et à l'export de DSF enregistrées dans un classeur Excel.

## Garanties du MVP

- Les noms d'en-têtes Excel ne sont jamais renommés.
- Les colonnes ne sont jamais supprimées ni réordonnées.
- Les doublons sont distingués par leur feuille, leur position et leur lettre Excel.
- La valeur originale reste conservée en base après une correction.
- Une fiche n'est validée que par une action explicite.
- L'export repart toujours de la copie immuable du classeur importé.
- Les corrections sont appliquées uniquement aux cellules concernées.
- Un journal d'audit est ajouté à l'export.
- Les mots de passe sont hachés et ne sont jamais stockés en clair dans SQLite.
- Chaque action de contrôle est attribuée automatiquement au compte connecté.
- Un contrôleur ne peut consulter et exporter que les DSF qui lui sont assignées.

Le projet prend désormais en charge plusieurs contrôleurs et un rôle administrateur. Avant une exposition sur Internet ou un usage simultané important, il faut néanmoins utiliser PostgreSQL, HTTPS, des sauvegardes et une politique de conservation des fichiers.

## Structure

```text
app/
  __init__.py
  extensions.py
  config/
    fiche_mapping.py
    validation_rules.py
  models/
    models.py
  routes/
    main.py
    dsf.py
    auth.py
    admin.py
    import_excel.py
    export_excel.py
  services/
    excel_service.py
    mapping_service.py
    dsf_service.py
    validation_service.py
    value_codec.py
    export_service.py
  templates/
  static/
config.py
run.py
requirements.txt
tests/
```

## Installation sous Windows PowerShell

Python 3.10 ou supérieur est requis.

```powershell
cd "D:\Stage INS\Application"
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Lancement

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

Ouvrir ensuite <http://127.0.0.1:5000>.

La base SQLite est créée automatiquement dans `instance/dsf_control.db`. Les copies originales et les exports sont également placés dans `instance/`, qui n'est pas versionné.

## Premier workflow

1. Ouvrir **Importer**.
2. Cliquer sur **Importer dsf.xlsx**, ou téléverser un autre fichier.
3. Rechercher une entreprise par NIU, numéro DSF, raison sociale ou sigle.
4. Ouvrir une DSF puis une fiche.
5. Modifier ou vérifier les cellules.
6. Valider explicitement chaque fiche, ou la déclarer non renseignée sur papier.
7. Exporter le classeur contrôlé depuis le tableau de bord.

## Comptes et rôles

Le compte administrateur initial est créé automatiquement au premier lancement :

```text
Nom d'utilisateur : irch
Mot de passe : 15081960irchdefluviaire
```

L'administrateur peut importer les classeurs, créer les comptes des contrôleurs, assigner chaque DSF et suivre leur progression. Les noms d'utilisateur doivent être entièrement en minuscules et les mots de passe comporter au moins 10 caractères.

Un contrôleur voit uniquement les DSF qui lui sont assignées. Son export contient les colonnes originales et uniquement ses lignes DSF ; les autres lignes et feuilles du classeur source ne lui sont pas transmises. L'administrateur conserve l'export complet du classeur.

Pour remplacer les identifiants d'initialisation avant la création d'une nouvelle base :

```powershell
$env:INITIAL_ADMIN_USERNAME = "administrateur"
$env:INITIAL_ADMIN_PASSWORD = "un-mot-de-passe-long-et-unique"
```

## Raccourcis

- `Entrée` : enregistrer la cellule et passer à la suivante ;
- `Tab` / `Maj+Tab` : cellule suivante / précédente ;
- flèches verticales : même colonne de la ligne précédente / suivante ;
- `F2` : sélectionner la valeur pour l'éditer ;
- `Ctrl+S` : sauvegarder la cellule active ;
- `Ctrl+F` : rechercher une variable dans la DSF ;
- `V` hors d'un champ : valider la fiche.

## Mapping des fiches

Le fichier `app/config/fiche_mapping.py` contient les 35 fiches et leur colonne de début. Le moteur repère les limites dans les en-têtes réels et conserve ensuite chaque variable originale.

Le mapping est volontairement strict : si un repère attendu disparaît, l'import s'arrête avec la liste des fiches manquantes. Cela évite d'associer silencieusement des centaines de variables à la mauvaise note.

Pour adapter une nouvelle version du formulaire, modifier uniquement les valeurs `start` dans `FICHE_DEFINITIONS`. Ne pas normaliser les en-têtes du classeur.

## Contrôles automatiques

Le fichier `app/config/validation_rules.py` paramètre les premières règles :

- `NET_N = BRUT - AMORT/DEPREC` pour le bilan actif ;
- `TOTAL GENERAL ACTIF = TOTAL GENERAL PASSIF`.

Les règles retournent un message, le niveau, les variables, les valeurs observée et attendue et l'écart. Elles ne corrigent jamais une cellule.

## Tests

```powershell
python -m pytest -q
```

### Tests navigateur avec Playwright

À la première installation, télécharger Chromium pour Playwright :

```powershell
python -m playwright install chromium
```

Le test `tests/e2e/test_playwright_workflow.py` lance une instance Flask et une base temporaires, puis vérifie dans un véritable navigateur la connexion, l'import, la création d'un contrôleur, l'affectation verrouillée et les restrictions d'accès. Il est inclus dans la commande générale `python -m pytest -q` et ne modifie jamais la base DSF réelle.

Les tests créent un classeur fictif avec deux DSF ayant le même NIU, deux colonnes `Ville`, une correction, une validation de fiche et un export contrôlé. Ils vérifient aussi la couleur et le journal de l'export.

## Configuration

Variables d'environnement facultatives :

```powershell
$env:SECRET_KEY = "une-cle-longue-et-aleatoire"
$env:DATABASE_URL = "sqlite:///D:/chemin/dsf_control.db"
```

En production, `SECRET_KEY` doit impérativement être remplacée et le serveur de développement Flask ne doit pas être exposé directement.

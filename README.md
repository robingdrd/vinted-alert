# vinted-alert

Bot de veille Vinted : chaque alerte est une **URL de recherche vinted.fr**.
Tous les filtres de l'URL (marque, taille, couleur, prix, état, matière...)
sont appliqués par Vinted côté serveur — ce que tu vois sur le site est
exactement ce que le bot surveille. Dès qu'un article jamais vu apparaît,
tu reçois un email récapitulatif + une notification push Android (ntfy).

Pas d'IA, pas de conseils de revente, pas de Telegram, pas (encore) de
scoring qualité. `scorer.py` reste dans le repo, prêt à être réactivé plus
tard pour un score de qualité basé sur l'historique de prix (déjà collecté
en tâche de fond dans `price_history.json`) et les mots-clés du titre.

L'historique de prix et la liste des articles déjà vus
sont stockés dans deux fichiers JSON (`price_history.json`,
`seen_items.json`), persistés entre les runs GitHub Actions via
`actions/cache`.

## Ajouter une alerte

1. Va sur **vinted.fr**, fais ta recherche et pose tes filtres normalement
   (marque, taille, couleur, prix...).
2. Copie l'URL de la barre d'adresse.
3. Lance :

```bash
python add_alert.py "<url collée>" --name mon_alerte --push
```

Le script affiche d'abord les articles qui correspondent **actuellement**,
pour que tu vérifies le filtre avant d'enregistrer. `--push` fait le
commit + push (sans lui, pense à le faire pour activer l'alerte sur
GitHub Actions). Pour supprimer une alerte : efface son bloc de 2 lignes
dans `config.yaml`, puis pousse.

💡 Filtre toujours par **marque** dans l'UI Vinted quand c'est pertinent :
la recherche par texte seul est floue (« clarks desert boot » remonte
aussi des chaussures d'autres marques).

⚠️ Le dédoublonnage est global : un article déjà notifié via une alerte ne
sera pas renotifié par une autre.

## Utilisation locale

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # renseigner EMAIL_EXPEDITEUR / EMAIL_MOT_DE_PASSE / EMAIL_DESTINATAIRE
python main.py
```

## Déploiement (GitHub Actions + cron-job.org)

Le bot ne tourne pas en continu : il est déclenché à la demande
(`workflow_dispatch`) par un ping externe toutes les 15 minutes.

### 1. Gmail

Génère un [mot de passe d'application Gmail](https://myaccount.google.com/apppasswords)
(nécessite la validation en 2 étapes activée sur le compte). C'est la
valeur à mettre dans `EMAIL_MOT_DE_PASSE` — pas le mot de passe du compte.

### 2. Secrets GitHub

Sur le repo GitHub (`Settings → Secrets and variables → Actions`), ajoute :

- `EMAIL_EXPEDITEUR` — adresse Gmail expéditrice
- `EMAIL_MOT_DE_PASSE` — le mot de passe d'application généré ci-dessus
- `EMAIL_DESTINATAIRE` — adresse qui reçoit les alertes

### 3. Personal Access Token GitHub

Génère un PAT (`Settings → Developer settings → Personal access tokens →
Fine-grained tokens`) avec la permission `Actions: Read and write` sur ce
repo. Ce token sert uniquement à déclencher le workflow depuis
cron-job.org — ne le mets jamais dans le repo lui-même.

### 4. cron-job.org

Crée un cronjob avec :

- **URL** : `https://api.github.com/repos/<owner>/vinted-alert/actions/workflows/vinted_alert.yml/dispatches`
- **Méthode** : `POST`
- **Headers** :
  - `Authorization: token <TON_PAT>`
  - `Accept: application/vnd.github.v3+json`
  - `Content-Type: application/json`
- **Body** : `{"ref":"main"}`
- **Fréquence** : toutes les 15 minutes

Vérifie dans l'onglet *Actions* du repo GitHub que les runs se déclenchent
et réussissent.

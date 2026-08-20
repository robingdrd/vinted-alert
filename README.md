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

## Ajouter une alerte (depuis le navigateur)

**Installation du raccourci, une seule fois :** crée un favori dans ta
barre de favoris et mets ceci comme *adresse* (à la place d'une URL) :

```
javascript:(function(){var u=location.href;if(u.indexOf('vinted.')<0){alert('Ouvre une recherche vinted.fr avant de cliquer');return;}var n=prompt('Nom de cette alerte ?','');if(n===null)return;window.open('https://github.com/robingdrd/vinted-alert/issues/new?title='+encodeURIComponent('Alerte: '+n)+'&body='+encodeURIComponent(u),'_blank');})();
```

**Ensuite, pour chaque nouvelle alerte :**

1. sur **vinted.fr**, fais ta recherche et pose tes filtres (marque,
   taille, couleur, prix... — tout est supporté) ;
2. clique sur le favori, donne un nom à l'alerte ;
3. une issue GitHub pré-remplie s'ouvre → clique **Submit new issue**.

Une minute plus tard, l'alerte est ajoutée et l'issue se ferme toute seule
avec la liste des articles qui correspondent déjà — c'est ce qui permet de
vérifier que les filtres sont les bons.

### Alternative en ligne de commande

```bash
python add_alert.py "<url collée>" --name mon_alerte --push
```

### Supprimer une alerte

Efface son bloc de 2 lignes dans [config.yaml](config.yaml) (l'éditeur web
de GitHub suffit : bouton ✏️, puis *Commit changes*).

### Bon à savoir

💡 Filtre toujours par **marque** dans l'UI Vinted quand c'est pertinent :
la recherche par texte seul est floue (« clarks desert boot » remonte
aussi des chaussures d'autres marques).

⚠️ Le dédoublonnage est global : un article déjà notifié via une alerte ne
sera pas renotifié par une autre.

⚠️ Une alerte trop large peut matcher des centaines d'articles, tous
notifiés au premier cycle. L'aperçu affiché dans l'issue annonce le nombre
à l'avance.

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

# Guide Utilisateur — Forex Pattern Detector

## Table des matières

1. [Installation](#installation)
2. [Données requises](#données-requises)
3. [Pipeline de détection (main.py)](#pipeline-de-détection)
4. [Scripts de validation visuelle](#scripts-de-validation-visuelle)
5. [Annotateur web](#annotateur-web)
6. [Configuration](#configuration)
7. [Structure des sorties](#structure-des-sorties)
8. [État d'implémentation des détecteurs](#état-dimplémentation-des-détecteurs)

---

## Installation

### Prérequis

- Python 3.11+

### Dépendances

```bash
pip install -r requirements.txt
pip install --pre mplfinance
```

---

## Données requises

### Format CSV

Placer les fichiers dans `data/raw/{PAIRE}/{TIMEFRAME}.csv` :

```
data/raw/
├── EURUSD/
│   ├── M15.csv
│   ├── M30.csv
│   ├── H1.csv
│   ├── H4.csv
│   ├── D.csv
│   └── W.csv
├── GBPUSD/
│   └── ...
```

Chaque CSV doit contenir les colonnes :

```csv
timestamp,open,high,low,close,volume
2020-01-02 00:00:00,1.12130,1.12250,1.12050,1.12200,1500
```

- `timestamp` : datetime UTC
- Les noms de colonnes sont insensibles à la casse
- Les doublons de timestamp sont automatiquement supprimés

### Paires supportées

`EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `AUDUSD`, `NZDUSD`, `USDCAD`, `GBPJPY`

### Timeframes supportés

| Fichier CSV | Clé interne |
|---|---|
| `M15` | M15 |
| `M30` | M30 |
| `H1` | H1 |
| `H4` | H4 |
| `D` | D1 |
| `W` | W1 |

---

## Pipeline de détection

Le pipeline principal (`main.py`) charge les données, détecte les patterns et génère des images annotées.

### Utilisation

```bash
# Une paire, un timeframe
python main.py --pair EURUSD --timeframe H4

# Plusieurs paires et timeframes
python main.py --pair EURUSD --pair GBPUSD --timeframe H4 --timeframe D1

# Toutes les combinaisons paire × timeframe
python main.py --all

# Mode debug
python main.py --all --log-level DEBUG
```

### Arguments

| Argument | Description |
|---|---|
| `--pair PAIRE` | Paire à traiter (répétable) |
| `--timeframe TF` | Timeframe à traiter (répétable) |
| `--all` | Traiter toutes les paires × tous les timeframes |
| `--log-level` | Niveau de log : `DEBUG`, `INFO` (défaut), `WARNING`, `ERROR` |

### Fonctionnement

1. **Chargement** des données CSV
2. **Enrichissement** : ajout de l'ATR(14) et du lissage Savitzky-Golay
3. **Détection des pivots** (swing highs/lows) sur tout le DataFrame
4. **Détection** des niveaux S/R, trendlines et figures chartistes
5. **Filtrage** : seuls les patterns avec confiance ≥ 0.55 sont rendus
6. **Génération d'images** PNG annotées (1920×1080, thème sombre)

Les images sont générées dans `output/{type_pattern}/{paire}/{timeframe}/`.

---

## Scripts de validation visuelle

Scripts dédiés pour valider visuellement chaque type de détection individuellement.

### Pivots

```bash
python scripts/test_pivots_visual.py
python scripts/test_pivots_visual.py --pair EURUSD --timeframes H4 D
python scripts/test_pivots_visual.py --window 300
```

Génère des charts avec les swing highs (▼ rouge) et swing lows (▲ teal) sur les N dernières bougies.

**Sortie :** `output/test/pivots/{PAIRE}/{TF}_pivots_last{N}.png`

### Niveaux S/R

```bash
python scripts/test_levels_visual.py
python scripts/test_levels_visual.py --pair EURUSD --timeframes H4 D
python scripts/test_levels_visual.py --window 300
```

Génère des charts avec les supports (teal) et résistances (rouge) sous forme de lignes horizontales et zones semi-transparentes.

**Sortie :** `output/test/levels/{PAIRE}/{TF}_levels_last{N}.png`

### Arguments communs

| Argument | Défaut | Description |
|---|---|---|
| `--pair PAIRE` | Toutes les paires disponibles | Paire(s) à traiter (répétable) |
| `--timeframes TF [...]` | Tous les CSV de la paire | Timeframes à traiter (séparés par espaces) |
| `--window N` | 500 | Nombre de bougies à afficher |

---

## Annotateur web

Application web interactive pour dessiner des annotations humaines sur les graphiques et les comparer aux détections algorithmiques.

### Démarrage

```bash
cd tools/annotator
python -m backend.server
```

Ouvrir http://localhost:8000 dans un navigateur.

### Barre supérieure

| Contrôle | Description |
|---|---|
| **Paire** | Sélection de la paire forex |
| **Timeframe** | Sélection du timeframe (se met à jour selon la paire) |
| **Bougies** | Nombre de bougies à charger (50–5000, défaut 500) |
| **Avant** | Date limite — charge les bougies antérieures à cette date |
| **Charger** | Charge le graphique avec les paramètres courants |
| **Courbe / Chandeliers** | Bascule entre affichage en chandeliers et en courbe |
| **Comparer** | Active le mode comparaison algo vs humain |
| **Masquer humain** | Affiche/masque les annotations humaines |
| **Algo** | Affiche/masque les détections algorithmiques |
| **Sauvegarder** | Sauvegarde manuelle (aussi via Ctrl+S, auto-save toutes les 30s) |

### Modes d'annotation

#### 1 — Niveaux (cliquer-glisser)

- Cliquer et glisser verticalement pour définir une zone de prix
- Un formulaire apparaît pour choisir Support ou Résistance et ajouter une note
- La zone s'étend de la bougie cliquée jusqu'au bord droit du graphique
- Chaque niveau reçoit un label auto-incrémenté (S1, S2... / R1, R2...)

#### 2 — Trendlines (deux clics)

- Premier clic : point d'ancrage 1 (accroché au high/low de la bougie)
- Second clic : point d'ancrage 2
- Le type (ascendant/descendant) est détecté automatiquement
- La ligne est prolongée jusqu'au bord droit du graphique
- Ascendant = teal, Descendant = rouge

#### 3 — Pivots (clic)

- Clic gauche : ajouter un pivot
- Clic droit : supprimer le pivot le plus proche (±2 bougies)
- Type (swing_high/swing_low) détecté selon la position du clic par rapport au milieu de la bougie
- L'importance (mineur/moyen/majeur) se règle via les boutons radio du panneau latéral
- Les pivots majeurs affichent une étoile (★)

#### 4 — Patterns

Interface prête, implémentation en cours.

### Raccourcis clavier

| Touche | Action |
|---|---|
| `1` `2` `3` `4` | Changer de mode d'annotation |
| `Ctrl+S` | Sauvegarder |
| `Ctrl+Z` | Annuler |
| `Ctrl+Y` / `Ctrl+Shift+Z` | Refaire |
| `Échap` | Annuler l'annotation en cours |
| `←` `→` | Défiler le graphique (10 bougies) |
| `+` `-` | Zoom avant/arrière (20%) |
| `Entrée` | Valider l'annotation en cours |

### Liste des annotations (panneau latéral)

- Affiche toutes les annotations avec label, plage de prix / direction / importance
- Cliquer sur un élément centre le graphique sur cette annotation
- Le bouton × supprime l'annotation (annulable avec Ctrl+Z)

### Notes sur les détections algo

Quand les détections algo sont visibles, double-cliquer sur une zone algo ouvre un formulaire de note. Les notes sont conservées et incluses dans le rapport de comparaison.

### Mode comparaison

Activé par le bouton **Comparer**. Affiche :

- **Cartes résumé** par type : nombre de matchs, faux positifs, faux négatifs, précision %, rappel %
- **Filtres** par catégorie (matchs, FP, FN)
- **Liste des divergences** — cliquer pour centrer le graphique
- Couleurs : bleu (match humain), vert (match algo), rouge (faux positif), orange (faux négatif)

### Stockage des annotations

Les annotations sont sauvegardées dans :

```
annotations/{PAIRE}/
├── {TF}_human.json          # annotations humaines
└── {TF}_comparison.json     # dernier rapport de comparaison
```

### API REST

| Méthode | Endpoint | Description |
|---|---|---|
| `GET` | `/api/pairs` | Paires et timeframes disponibles |
| `GET` | `/api/candles` | Données OHLCV (params: `pair`, `timeframe`, `last_n`, `before`) |
| `POST` | `/api/annotations` | Sauvegarder les annotations humaines |
| `GET` | `/api/annotations` | Charger les annotations sauvegardées |
| `GET` | `/api/detections` | Lancer les détections algo et récupérer les résultats |
| `GET` | `/api/compare` | Comparer humain vs algo, retourne le rapport |

---

## Configuration

Tous les paramètres ajustables sont dans `src/config.py` via le dictionnaire `DEFAULT_CONFIG`.

### Paramètres de détection

| Paramètre | Défaut | Description |
|---|---|---|
| `pivot_left_bars` | 5 | Barres à gauche pour confirmer un pivot |
| `pivot_right_bars` | 5 | Barres à droite pour confirmer un pivot |
| `level_min_touches` | 3 | Touches minimum pour valider un niveau S/R |
| `level_lookback_bars` | 600 | Fenêtre de lookback pour le calcul KDE |
| `trendline_min_touches` | 3 | Touches minimum pour une trendline |
| `trendline_min_r_squared` | 0.85 | R² minimum RANSAC pour les trendlines |
| `trendline_lookback_bars` | 600 | Fenêtre de lookback pour les trendlines |
| `context_window_size` | 600 | Taille de la fenêtre de contexte par pivot |

### Paramètres de rendu

| Paramètre | Défaut | Description |
|---|---|---|
| `render_candle_window` | 600 | Nombre de bougies affichées par image |
| `render_min_confidence` | 0.55 | Confiance minimum pour générer une image |
| `render_dpi` | 100 | Résolution des images PNG |
| `render_figsize` | (19.2, 10.8) | Taille de la figure (→ 1920×1080 px) |

---

## Structure des sorties

### Pipeline principal

```
output/
├── support/{PAIRE}/{TF}/          # Niveaux de support
├── resistance/{PAIRE}/{TF}/       # Niveaux de résistance
├── swing_high/{PAIRE}/{TF}/       # Pivots hauts
├── swing_low/{PAIRE}/{TF}/        # Pivots bas
├── trendline_up/{PAIRE}/{TF}/     # Trendlines ascendantes
├── trendline_down/{PAIRE}/{TF}/   # Trendlines descendantes
├── double_top/{PAIRE}/{TF}/
├── double_bottom/{PAIRE}/{TF}/
├── head_shoulders/{PAIRE}/{TF}/
├── inv_head_shoulders/{PAIRE}/{TF}/
├── triangle_asc/{PAIRE}/{TF}/
├── triangle_desc/{PAIRE}/{TF}/
├── flag/{PAIRE}/{TF}/
└── consolidation/{PAIRE}/{TF}/
```

Nom des fichiers : `{PAIRE}_{TF}_{timestamp}.png`

### Scripts de test

```
output/test/
├── pivots/{PAIRE}/{TF}_pivots_last{N}.png
└── levels/{PAIRE}/{TF}_levels_last{N}.png
```

---

## État d'implémentation des détecteurs

| Détecteur | Statut | Description |
|---|---|---|
| **PivotDetector** | ✅ Implémenté | Multi-échelle (3 niveaux), scipy find_peaks |
| **LevelDetector** | ✅ Implémenté | KDE gaussien, tolérance adaptative par TF |
| **TrendlineDetector** | ⬜ Squelette | RANSAC prévu |
| **DoubleDetector** | ⬜ Squelette | Double top/bottom |
| **HeadShouldersDetector** | ⬜ Squelette | Épaule-Tête-Épaule |
| **TriangleDetector** | ⬜ Squelette | Triangles ascendant/descendant |
| **FlagDetector** | ⬜ Squelette | Drapeaux haussier/baissier |
| **ConsolidationDetector** | ⬜ Squelette | Consolidation (test ADF) |

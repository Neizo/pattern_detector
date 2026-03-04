# CLAUDE.md — Forex Price Action Pattern Detector

## Résumé du projet
Détection automatique de patterns de price action sur les paires forex majeures (20 ans de données historiques), avec génération d'images pour chaque détection.

## Objectif final
Le but du projet est la **détection automatique** de patterns de price action
(pivots, trendlines, supports/résistances, figures chartistes) sur données
historiques forex.

Le livrable principal est un **ensemble d'images annotées** : pour chaque
pattern détecté, le pipeline génère une capture du graphique en chandeliers
montrant N bougies en arrière depuis le point de détection, avec les
annotations visuelles du pattern (key points, lignes, zones).

Ces images sont destinées à une **validation visuelle humaine**. L'humain
parcourt les images classées par type de pattern et évalue si les détections
sont pertinentes. Ce feedback guide l'ajustement des seuils et du scoring.

Le pipeline ne prend aucune décision de trading. Il produit des détections
candidates que l'humain valide ou rejette.

## Architecture : Pipeline en 3 étapes
```
CSV (OHLCV) → [LOAD] → [PRÉ-CALCUL PIVOTS] → [DETECT] → [RENDER] → Images classées par pattern
```
Les pivots (swing highs/lows) sont pré-calculés en batch sur tout le DataFrame, puis interrogés par index par les détecteurs suivants. Voir ARCHITECTURE.md pour le détail.

## Stack technique
- **Python 3.11+**
- **pandas** : chargement et manipulation des données OHLCV
- **numpy** : calculs vectorisés
- **scipy** : `savgol_filter` (débruitage), `find_peaks` (pivots), `gaussian_kde` (niveaux S/R)
- **scikit-learn** : `RANSACRegressor` (trendlines, triangles, drapeaux)
- **statsmodels** : `adfuller` (test de stationnarité pour consolidations)
- **mplfinance** : génération de charts en chandeliers japonais
- **matplotlib** : annotations (lignes de tendance, supports/résistances, zones)

## Format des données source
```
Fichiers CSV dans : data/raw/{pair}/{timeframe}/
Colonnes : timestamp,open,high,low,close,volume
Paires : EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD
Timeframes : M15, M30, H1, H4, D1, W1
```

## Structure du projet
```
forex-patterns/
├── CLAUDE.md
├── docs/
│   ├── ARCHITECTURE.md      # Pipeline détaillé & flow de données
│   ├── PATTERNS.md           # Définition de chaque pattern & règles de détection
│   └── CONVENTIONS.md        # Style de code, nommage, tests
├── src/
│   ├── __init__.py
│   ├── loader/               # Étape 1 : chargement & normalisation CSV
│   │   ├── __init__.py
│   │   └── csv_loader.py
│   ├── detector/             # Étape 2 : détection des patterns
│   │   ├── __init__.py
│   │   ├── pivots.py         # Points hauts/bas (swing highs/lows)
│   │   ├── trendlines.py     # Droites de tendance
│   │   ├── levels.py         # Supports & résistances
│   │   └── patterns/         # Figures chartistes
│   │       ├── __init__.py
│   │       ├── double.py     # Double top / double bottom
│   │       ├── head_shoulders.py  # ETE & ETE inversé
│   │       ├── triangles.py  # Triangles ascendant/descendant
│   │       ├── flag.py       # Drapeaux
│   │       └── consolidation.py
│   ├── renderer/             # Étape 3 : génération d'images
│   │   ├── __init__.py
│   │   └── chart_renderer.py
│   └── pipeline.py           # Orchestrateur principal
├── scripts/                  # Scripts de validation visuelle (1 par pattern)
│   ├── test_pivots_visual.py
│   ├── test_levels_visual.py
│   ├── test_trendlines_visual.py   # (à créer)
│   ├── test_double_visual.py       # (à créer)
│   ├── test_head_shoulders_visual.py
│   ├── test_triangles_visual.py
│   ├── test_flag_visual.py
│   └── test_consolidation_visual.py
├── output/
│   ├── test/                 # Images de validation visuelle (scripts/)
│   │   ├── pivots/{PAIR}/    #   ex: pivots/EURUSD/M30_pivots_last500.png
│   │   ├── levels/{PAIR}/
│   │   ├── trendlines/{PAIR}/
│   │   ├── double/{PAIR}/
│   │   └── ...
│   ├── double_top/           # Images pipeline production (main.py)
│   ├── double_bottom/
│   ├── head_shoulders/
│   ├── inv_head_shoulders/
│   ├── triangle_asc/
│   ├── triangle_desc/
│   ├── flag/
│   ├── consolidation/
│   └── trendline/
├── data/
│   └── raw/                  # CSVs source
├── tests/
├── requirements.txt
└── main.py                   # Point d'entrée CLI
```
## Ordre d'implémentation recommandé
1. config.py + dataclasses (PatternResult, Pivot, PivotStore)
2. CSVLoader (testable isolément avec un CSV réel)
3. Enricher (ATR + Savgol)
4. PivotDetector + PivotStore (premier test visuel possible)
5. Pipeline squelette (boucle sur pivots, sans détecteurs)
6. Renderer basique (chandeliers + marqueurs de pivots)
7. LevelDetector (KDE)
8. TrendlineDetector (RANSAC)
9. Patterns un par un : double → H&S → triangles → flag → consolidation

## Scripts de validation visuelle
Chaque détecteur implémenté **doit** avoir un script `scripts/test_{pattern}_visual.py` associé.

### Convention obligatoire
- **Sortie** : `output/test/{pattern}/{PAIR}/{TF}_{pattern}_last{window}.png`
- **Arguments CLI** : `--pair` (répétable), `--timeframes`, `--window` (défaut 500)
- **Timeframe** : passer `tf_key` (clé canonique via `TF_MAP`) au détecteur, pas `tf_stem`
- **Renderer** : rediriger `OUTPUT_ROOT` vers `out_dir` (= `OUTPUT_BASE / pair`)
- **Modèle** : suivre la structure de `test_levels_visual.py` ou `test_pivots_visual.py`

### Exemple d'utilisation
```bash
py scripts/test_levels_visual.py --pair EURUSD --timeframes M30 H4
py scripts/test_pivots_visual.py --pair GBPUSD --window 300
```

## Références détaillées
- **Architecture & pipeline** → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Définition des patterns** → [docs/PATTERNS.md](docs/PATTERNS.md)
- **Conventions de code** → [docs/CONVENTIONS.md](docs/CONVENTIONS.md)
- **Guide utilisateur** → [docs/USER_GUIDE.md](docs/USER_GUIDE.md)

## Pièges à éviter
- Ne PAS utiliser `df.iloc[-500:]` pour la fenêtre de rendu → utiliser `end_index` du PatternResult
- Ne PAS recalculer les pivots dans chaque détecteur → toujours passer le PivotStore
- Ne PAS importer mplfinance dans les détecteurs → import uniquement dans renderer/

## Règles pour Claude (assistant IA)
1. **Toujours lire les 3 fichiers docs/** avant de coder quoi que ce soit
2. **Respecter le pipeline** : ne jamais mélanger load/detect/render dans un même module
3. **Chaque détection retourne un `PatternResult`** (voir ARCHITECTURE.md)
4. **Chaque image = bougie courante + 500 bougies en arrière**, annotée avec le pattern détecté
5. **Tester sur au moins 2 timeframes différents** avant de valider un algorithme
6. **Typage strict** : utiliser les type hints partout, dataclasses pour les structures
7. **Pas de dépendances inutiles** : se limiter au stack listé ci-dessus
8. **Seuils adaptatifs** : TOUS les seuils de prix/distance sont exprimés en multiples d'ATR(14), jamais en % fixe (voir PATTERNS.md)
9. **RANSAC** pour tout fitting linéaire (trendlines, bords de triangles, canaux)
10. **Savitzky-Golay** uniquement pour le pré-calcul des pivots, pas sur les données brutes
11. **Mettre à jour `docs/USER_GUIDE.md`** à chaque ajout ou modification de fonctionnalité (nouveau détecteur, nouveau script, nouvel endpoint API, nouveau raccourci clavier, nouveau paramètre de config, etc.)

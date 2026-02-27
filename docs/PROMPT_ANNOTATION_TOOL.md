# Prompt pour Claude Code — Outil d'annotation web et comparaison algo/humain

## Contexte

Je développe une bibliothèque Python de détection de patterns de price action (pivots, levels S/R, trendlines, figures chartistes). Les algos de détection fonctionnent mais produisent trop de résultats non pertinents. J'ai besoin d'un outil pour annoter manuellement mes propres détections sur un chart, puis comparer systématiquement mes annotations humaines avec les résultats algorithmiques pour identifier les règles de filtrage manquantes.

## Architecture de l'outil

L'outil est **séparé de la lib de détection**. Il vit dans `tools/annotator/` à la racine du projet et se compose de :

```
tools/annotator/
├── backend/
│   ├── server.py             # FastAPI, sert les données et orchestre la comparaison
│   ├── data_provider.py      # Interface avec CSVLoader + detection lib
│   └── comparator.py         # Logique de comparaison algo vs humain
├── frontend/
│   ├── index.html            # SPA unique
│   ├── app.js                # Logique principale
│   ├── chart.js              # Wrapper TradingView Lightweight Charts
│   ├── annotations.js        # Gestion des annotations (création, édition, suppression)
│   ├── comparison.js         # Affichage overlay comparaison
│   └── styles.css
├── requirements.txt          # fastapi, uvicorn (dépendances outil uniquement)
└── README.md
```

**Règle de dépendance** : `tools/annotator/backend/` importe depuis `src/detection/` et `src/loader/`. Jamais l'inverse. L'outil n'est PAS un composant de la lib.

## Stack technique

### Backend
- **FastAPI** avec **uvicorn** — serveur local uniquement
- Importe la lib `detection/` existante pour exécuter les détections
- Importe le `CSVLoader` existant pour charger les données
- Sert le frontend en fichiers statiques

### Frontend
- **TradingView Lightweight Charts** (https://github.com/nickvdyck/lightweight-charts) via CDN — rendu des chandeliers
- **Vanilla JS** — pas de framework React/Vue, l'outil doit rester simple
- **CSS** minimal, dark theme pour être cohérent avec un chart financier

## API Backend

### GET /api/pairs
Retourne la liste des paires et timeframes disponibles dans `data/raw/`.
```json
{
  "pairs": [
    {"pair": "EURUSD", "timeframes": ["M15", "M30", "H1", "H4", "D1"]},
    {"pair": "GBPJPY", "timeframes": ["M15", "M30", "H1", "H4", "D1"]}
  ]
}
```

### GET /api/candles?pair=EURUSD&timeframe=H4&last_n=500&before=2025-12-31
Retourne les N dernières bougies avant la date spécifiée.
```json
{
  "pair": "EURUSD",
  "timeframe": "H4",
  "candles": [
    {"timestamp": "2024-07-15T08:00:00Z", "open": 1.0832, "high": 1.0855, "low": 1.0820, "close": 1.0847, "volume": 12340}
  ]
}
```

### GET /api/detections?pair=EURUSD&timeframe=H4&last_n=500&before=2025-12-31
Exécute la détection algorithmique sur la même fenêtre et retourne les résultats groupés par type.
```json
{
  "pivots": [
    {"index": 42, "timestamp": "...", "price": 1.0855, "pivot_type": "swing_high", "strength": 2, "prominence": 0.0023}
  ],
  "levels": [
    {"price": 1.0847, "type": "resistance", "strength": 0.82, "touches": 5, "scores": {"normalized_touches": 0.8, "temporal_spread": 0.7, "avg_reaction": 0.9, "recency": 0.6}}
  ],
  "trendlines": [
    {"slope": 0.00012, "intercept": 1.0750, "type": "ascending", "n_inliers": 4, "anchor_points": [{"index": 10, "price": 1.0780}, {"index": 85, "price": 1.0820}], "scores": {}}
  ],
  "patterns": [
    {"pattern_type": "double_top", "confidence": 0.78, "key_points": [{"label": "H1", "index": 30, "price": 1.0855}, {"label": "L", "index": 55, "price": 1.0790}, {"label": "H2", "index": 80, "price": 1.0850}], "annotations": {"neckline": 1.0790, "confirmed": false}, "scores": {}}
  ]
}
```

### POST /api/annotations
Sauvegarde les annotations humaines.
```json
{
  "pair": "EURUSD",
  "timeframe": "H4",
  "window": {"last_n": 500, "before": "2025-12-31"},
  "annotations": {
    "levels": [
      {"price_high": 1.0855, "price_low": 1.0842, "type": "resistance", "note": "rejeté 3 fois nettement"}
    ],
    "trendlines": [
      {"points": [{"index": 10, "price": 1.0780}, {"index": 85, "price": 1.0820}], "type": "ascending", "note": ""}
    ],
    "pivots": [
      {"index": 42, "type": "swing_high", "importance": "major"}
    ],
    "patterns": [
      {"pattern_type": "double_top", "key_points": [{"label": "H1", "index": 30, "price": 1.0855}, {"label": "L", "index": 55, "price": 1.0790}, {"label": "H2", "index": 80, "price": 1.0850}], "note": ""}
    ]
  }
}
```
Sauvegardé dans `annotations/{pair}_{timeframe}_human.json`.

### GET /api/compare?pair=EURUSD&timeframe=H4
Charge les annotations humaines et les détections algo, exécute la comparaison, retourne le rapport.

## Logique de comparaison (comparator.py)

### Critères de matching par type

**Levels** :
- Match si le prix algo tombe DANS la zone humaine [price_low, price_high]
- OU si la distance entre le prix algo et le bord le plus proche de la zone < 0.3 × ATR (tolérance pour les quasi-matchs)
- Un level algo ne peut matcher qu'une seule zone humaine (la plus proche)
- Une zone humaine ne peut être matchée que par un seul level algo (le plus proche du centre)

**Pivots** :
- Match si même type (swing_high/swing_low) ET même bougie ± 2 bougies

**Trendlines** :
- Match si même type (ascending/descending) ET pente similaire ± 15% ET au moins 2 points d'ancrage en commun (± 3 bougies)

**Patterns** :
- Match si même type de pattern ET key_points qui se chevauchent (± 5 bougies sur chaque key_point, au moins 2/3 des key_points matchent)

### Rapport structuré

Pour chaque type (levels, pivots, trendlines, patterns), trois catégories :

**Matched (vrais positifs)** : détections algo correspondant à une annotation humaine, avec les métriques détaillées des deux côtés et la distance/écart.

**False positives** : détections algo SANS correspondance humaine, avec toutes les métriques du PatternResult + la distance à l'annotation humaine la plus proche (pour voir si l'algo est "proche" ou complètement à côté).

**False negatives** : annotations humaines SANS correspondance algo, avec les données de contexte brutes (pivots dans la zone, densité KDE au prix annoté, etc.) pour comprendre pourquoi l'algo a raté.

### Format du rapport JSON

```json
{
  "pair": "EURUSD",
  "timeframe": "H4",
  "window": {"start": "2024-07-15T08:00:00Z", "end": "2025-12-31T00:00:00Z", "n_candles": 500},
  "atr_median": 0.0045,
  "summary": {
    "levels": {"matched": 4, "false_positives": 8, "false_negatives": 1, "precision": 0.33, "recall": 0.80},
    "pivots": {"matched": 30, "false_positives": 15, "false_negatives": 5, "precision": 0.67, "recall": 0.86},
    "trendlines": {"matched": 2, "false_positives": 3, "false_negatives": 1, "precision": 0.40, "recall": 0.67},
    "patterns": {"matched": 1, "false_positives": 2, "false_negatives": 0, "precision": 0.33, "recall": 1.0}
  },
  "levels": {
    "matched": [
      {
        "human": {"price_high": 1.0855, "price_low": 1.0842, "type": "resistance", "note": "rejeté 3 fois"},
        "algo": {"price": 1.0847, "strength": 0.82, "touches": 5, "type": "resistance", "scores": {"normalized_touches": 0.8, "temporal_spread": 0.7, "avg_reaction": 0.9, "recency": 0.6}},
        "algo_inside_zone": true,
        "distance_to_zone_center_atr": 0.04
      }
    ],
    "false_positives": [
      {
        "algo": {"price": 1.0812, "strength": 0.45, "touches": 2, "scores": {}},
        "nearest_human_zone": {"price_high": 1.0855, "price_low": 1.0842, "distance_to_nearest_edge_atr": 0.5},
        "diagnosis": "low_touches"
      }
    ],
    "false_negatives": [
      {
        "human": {"price_high": 1.0925, "price_low": 1.0915, "type": "resistance", "note": "zone claire en D1"},
        "nearest_algo": {"price": 1.0905, "distance_to_zone_edge_atr": 0.15},
        "context": {
          "pivots_in_zone": [{"index": 120, "price": 1.0920, "type": "swing_high"}],
          "kde_density_at_zone_center": 0.02,
          "n_candles_touching_zone": 8
        }
      }
    ]
  },
  "pivots": { "matched": [], "false_positives": [], "false_negatives": [] },
  "trendlines": { "matched": [], "false_positives": [], "false_negatives": [] },
  "patterns": { "matched": [], "false_positives": [], "false_negatives": [] }
}
```

Sauvegardé dans `annotations/{pair}_{timeframe}_comparison.json`.

## Interface web — Fonctionnalités

### Sélection des données
- Dropdowns en haut : Paire, Timeframe, nombre de bougies (défaut 500), date de fin (défaut 2025-12-31)
- Bouton "Charger" → appelle GET /api/candles et affiche le chart

### Chart
- TradingView Lightweight Charts en mode chandeliers
- Dark theme
- Zoom molette, navigation drag (comportement natif de Lightweight Charts)
- Le chart occupe ~75% de la largeur, un panneau latéral occupe ~25%

### Panneau latéral — Mode annotation
Barre de boutons pour switcher de mode : Levels | Trendlines | Pivots | Patterns

**Mode Levels** :
- Je clique-glisse verticalement sur le chart → rectangle semi-transparent entre les deux prix (toute la largeur du chart)
- Couleur : bleu semi-transparent
- Après le tracé, un mini-formulaire apparaît dans le panneau latéral :
  - Type : boutons radio Support / Resistance
  - Note : champ texte libre
  - Boutons Valider / Supprimer
- Les zones annotées restent affichées avec un label (S1, S2, R1, R2...)

**Mode Trendlines** :
- Je clique sur un premier point du chart (snapping à la bougie la plus proche : high pour les résistances, low pour les supports)
- Je clique sur un deuxième point → la droite se trace et s'étend
- Mini-formulaire : Type ascending/descending (auto-détecté par la pente), Note
- La trendline est affichée en bleu, extended au-delà des points d'ancrage

**Mode Pivots** :
- Je clique sur une bougie → marqueur triangle (▲ swing_high au-dessus, ▼ swing_low en-dessous)
- Auto-détection du type basé sur la position du clic (moitié haute = swing_high, moitié basse = swing_low)
- Mini-formulaire : Importance (minor/medium/major), possibilité de corriger le type

**Mode Patterns** :
- Sélection du type de pattern dans le panneau latéral (dropdown ou boutons)
- Pour chaque type, affichage de la séquence de key_points attendue :
  - Double top : "Cliquez H1 → L → H2"
  - Double bottom : "Cliquez L1 → H → L2"
  - Head & Shoulders : "Cliquez EG → L1 → T → L2 → ED"
  - Inv H&S : "Cliquez EG → H1 → T → H2 → ED"
  - Triangle asc : "Cliquez 4+ points alternés (highs sur résistance, lows sur support ascendant)"
  - Triangle desc : "Cliquez 4+ points alternés"
  - Flag : "Cliquez pole_start → pole_end → 4+ points du canal"
  - Consolidation : "Cliquez 4+ points alternés dans le range"
- Les key_points sont reliés par des lignes en pointillés au fur et à mesure
- Mini-formulaire : Note, bouton Valider / Annuler

### Panneau latéral — Liste des annotations
- Liste scrollable de toutes les annotations, groupées par type
- Chaque annotation est cliquable (zoom le chart sur cette zone)
- Bouton supprimer (icône poubelle) sur chaque annotation
- Compteur par type : "Levels: 5 | Pivots: 12 | Trendlines: 3 | Patterns: 2"

### Sauvegarde
- Bouton "Sauvegarder" → POST /api/annotations
- Auto-save toutes les 30 secondes (pour ne pas perdre le travail)
- Indicateur visuel : "Sauvegardé ✓" / "Non sauvegardé •"

### Mode comparaison
- Bouton "Comparer avec l'algo" → GET /api/compare
- Le chart passe en mode overlay :
  - Annotations humaines : BLEU (zones semi-transparentes pour levels, lignes pour trendlines, marqueurs pour pivots)
  - Détections algo matchées : VERT (affichées en superposition)
  - Faux positifs algo : ROUGE pointillé
  - Faux négatifs (annotations humaines non matchées) : ORANGE pointillé
- Le panneau latéral affiche le rapport :
  - Résumé : precision/recall par type
  - Liste des divergences cliquables (clic → zoom sur le chart)
  - Pour chaque faux positif : les scores détaillés de l'algo (pour comprendre pourquoi il a détecté)
  - Pour chaque faux négatif : le contexte (pivots proches, densité KDE, etc.)
- Toggle pour afficher/masquer chaque catégorie (matched, FP, FN) indépendamment

## Contraintes techniques

- Le backend FastAPI sert le frontend en fichiers statiques (un seul serveur, pas de build step)
- TradingView Lightweight Charts importé via CDN (https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js)
- Vanilla JS uniquement côté frontend — pas de React, Vue, ni bundler. L'outil doit rester simple à lancer.
- Le backend importe `src.detection` et `src.loader` — il utilise la lib existante, ne réimplémente rien.
- Les annotations sont stockées dans `annotations/` à la racine du projet en JSON.
- Dark theme obligatoire (fond sombre, texte clair, cohérent avec les charts financiers)
- L'outil tourne exclusivement en local (localhost)

## Lancement

```bash
# Depuis la racine du projet
cd tools/annotator
pip install -r requirements.txt
python -m backend.server
# → ouvre http://localhost:8000
```

## Ce que je ferai avec les résultats

J'analyserai les faux positifs pour trouver les règles de filtrage manquantes (fusion de niveaux proches, pondération de la récence, qualité de réaction minimale). Les faux négatifs me diront si mes seuils sont trop stricts. Les métriques precision/recall par type me donneront un score objectif de la qualité de chaque détecteur, que je pourrai suivre au fil des itérations d'amélioration.

## Ordre d'implémentation

1. Backend : endpoints /api/candles et /api/pairs (vérifier que les données se chargent)
2. Frontend : chart basique avec Lightweight Charts (afficher les bougies)
3. Frontend : mode annotation Levels (zones) — c'est le plus prioritaire
4. Frontend : modes Pivots et Trendlines
5. Frontend : mode Patterns
6. Backend : endpoint /api/detections (brancher la lib existante)
7. Backend : comparator.py + endpoint /api/compare
8. Frontend : mode comparaison avec overlay
9. Sauvegarde/chargement des annotations
10. Polish : auto-save, labels, UX

Commence par lire les fichiers docs/ARCHITECTURE.md, docs/PATTERNS.md et docs/CONVENTIONS.md pour comprendre la structure de la lib de détection existante, puis implémente dans l'ordre ci-dessus.

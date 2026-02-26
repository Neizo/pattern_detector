# Forex Price Action Pattern Detector

Détection automatique de patterns de price action sur les paires forex majeures, avec génération d'images annotées pour validation visuelle humaine.

## Objectif

Le pipeline analyse des données OHLCV historiques (20 ans, CSV), détecte des patterns chartistes et génère une image par détection — chandeliers japonais annotés avec les points clés du pattern. L'humain parcourt ensuite les images classées par type pour valider ou rejeter les détections et affiner les seuils.

**Le pipeline ne prend aucune décision de trading.**

## Pipeline

```
CSV (OHLCV)
  └── Loader          → DataFrame propre (DatetimeIndex UTC)
  └── Enricher        → ATR(14) + Savitzky-Golay (smoothed_high/low)
  └── PivotDetector   → PivotStore (swing highs/lows, multi-échelle)
  └── Détecteurs      → list[PatternResult]
        ├── LevelDetector      (supports/résistances — KDE)
        ├── TrendlineDetector  (droites de tendance — RANSAC)
        └── Patterns/
              ├── DoubleDetector       (double top / double bottom)
              ├── HeadShouldersDetector
              ├── TriangleDetector
              ├── FlagDetector
              └── ConsolidationDetector
  └── ChartRenderer   → PNG 1920×1080 par pattern
```

## Structure

```
pattern_detector/
├── main.py                     # CLI (--pair, --timeframe, --all)
├── requirements.txt
├── src/
│   ├── config.py               # Configuration centralisée (DEFAULT_CONFIG)
│   ├── models.py               # Dataclasses : PatternResult, Pivot, PatternType
│   ├── enricher.py             # ATR(14) + Savitzky-Golay
│   ├── pipeline.py             # Orchestrateur principal
│   ├── loader/
│   │   └── csv_loader.py       # Chargement CSV → DataFrame
│   ├── detector/
│   │   ├── pivots.py           # PivotDetector + PivotStore (multi-échelle)
│   │   ├── levels.py           # Supports/résistances (KDE)
│   │   ├── trendlines.py       # Trendlines (RANSAC)
│   │   └── patterns/
│   │       ├── double.py
│   │       ├── head_shoulders.py
│   │       ├── triangles.py
│   │       ├── flag.py
│   │       └── consolidation.py
│   └── renderer/
│       └── chart_renderer.py   # mplfinance + annotations
├── scripts/
│   └── test_pivots_visual.py   # Validation visuelle des pivots
├── tests/
│   ├── test_loader.py
│   ├── test_enricher.py
│   └── test_pivots.py
├── data/raw/                   # CSVs source (non versionnés)
│   └── {PAIR}/{TIMEFRAME}.csv
├── output/                     # Images générées (non versionnées)
│   └── {pattern_type}/
└── docs/
    ├── ARCHITECTURE.md
    ├── PATTERNS.md
    └── CONVENTIONS.md
```

## Format des données

```
Chemin  : data/raw/{PAIR}/{TIMEFRAME}.csv
Colonnes: timestamp, open, high, low, close, volume
Paires  : EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, NZDUSD, USDCAD
TF      : M15, M30, H1, H4, D1, W1
```

## Installation

```bash
git clone https://github.com/Neizo/pattern_detector.git
cd pattern_detector
pip install -r requirements.txt
```

> **Note :** `mplfinance` n'est disponible qu'en pre-release. Il est installé automatiquement via `requirements.txt` avec la version épinglée `0.12.10b0`.

## Utilisation

```bash
# Une paire / un timeframe
python main.py --pair EURUSD --timeframe H4

# Plusieurs combinaisons
python main.py --pair EURUSD --pair GBPUSD --timeframe H4 --timeframe D1

# Toutes les paires et tous les timeframes
python main.py --all

# Validation visuelle des pivots (script dédié)
python scripts/test_pivots_visual.py
python scripts/test_pivots_visual.py --timeframes H4 D --window 300
```

Les images sont générées dans `output/{pattern_type}/`.

## Stack technique

| Lib | Usage |
|---|---|
| pandas / numpy | Chargement et manipulation OHLCV |
| scipy | `savgol_filter` (lissage), `find_peaks` (pivots), `gaussian_kde` (S/R) |
| scikit-learn | `RANSACRegressor` (trendlines, triangles, drapeaux) |
| statsmodels | `adfuller` (test de stationnarité — consolidations) |
| mplfinance | Charts en chandeliers japonais |
| matplotlib | Annotations (lignes, zones, marqueurs) |

## Conventions clés

- **Tous les seuils** sont en multiples d'ATR(14) — jamais en % fixe
- **RANSAC** pour tout fitting linéaire (trendlines, bords de triangles)
- **Savitzky-Golay** uniquement pour le pré-calcul des pivots
- **Pas de décision cross-timeframe** — chaque run (pair, timeframe) est indépendant
- **Chaque détecteur** retourne `list[PatternResult]`, jamais `None`

## Tests

```bash
pytest tests/ -v
```

## État d'avancement

| Composant | Statut |
|---|---|
| CSVLoader | Implémenté |
| Enricher (ATR + Savgol) | Implémenté |
| PivotDetector + PivotStore | Implémenté |
| ChartRenderer | Implémenté |
| Pipeline (orchestrateur) | Implémenté |
| LevelDetector (KDE) | À faire |
| TrendlineDetector (RANSAC) | À faire |
| DoubleDetector | À faire |
| HeadShouldersDetector | À faire |
| TriangleDetector | À faire |
| FlagDetector | À faire |
| ConsolidationDetector | À faire |

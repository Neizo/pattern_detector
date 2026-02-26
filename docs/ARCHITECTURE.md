# ARCHITECTURE.md — Pipeline & Structures de données

## Vue d'ensemble du pipeline

```
main.py
  └── Pipeline.run(pair, timeframe)
        ├── 1.   Loader.load(pair, timeframe) → pd.DataFrame (complet)
        ├── 1.5  Enricher.enrich(df, timeframe) → pd.DataFrame (+ colonnes ATR, smoothed)
        ├── 2.0  PivotDetector.compute_all(df) → PivotStore (batch, une seule fois)
        ├── 2.1  Itération sur les pivots : pour chaque pivot P du PivotStore :
        │         ├── Fenêtre de contexte = [P.index - W, P.index] (W = context_window_size)
        │         ├── Les détecteurs cherchent les patterns dont P est le DERNIER élément
        │         └── Accumulation des PatternResult (pas de déduplication nécessaire)
        └── 3.   Renderer.render(df, pattern_result) → image par pattern détecté
```

## Étape 1 : Loader

**Responsabilité** : charger un CSV, valider les colonnes, indexer par timestamp.

```python
# src/loader/csv_loader.py
class CSVLoader:
    def load(self, pair: str, timeframe: str) -> pd.DataFrame:
        """
        - Lit data/raw/{pair}/{timeframe}/*.csv
        - Valide colonnes : timestamp, open, high, low, close, volume
        - Convertit timestamp → DatetimeIndex (UTC)
        - Trie par date croissante, supprime les doublons
        - Retourne un DataFrame propre
        """
```

**Contraintes** :
- Le loader ne fait AUCUNE détection. Il ne calcule rien.
- Gérer les fichiers CSV multi-parties (concaténation si plusieurs fichiers par paire/tf)
- Les volumes à 0 sont acceptés (certains feeds forex n'ont pas de volume réel)

## Étape 1.5 : Enricher

**Responsabilité** : ajouter les colonnes calculées nécessaires à tous les détecteurs. Appelé une seule fois après le chargement, avant toute détection.

```python
# src/enricher.py
class Enricher:
    def enrich(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """
        1. Calcul de l'ATR(14) Wilder → colonne df['atr']
           tr = max(high - low, |high - close_prev|, |low - close_prev|)
           atr = EMA(tr, span=14)

        2. Lissage Savitzky-Golay → colonnes df['smoothed_high'], df['smoothed_low']
           Paramètres adaptatifs par timeframe :
             - M15/M30 : window=11, polyorder=3
             - H1/H4   : window=7,  polyorder=3
             - D1/W1   : window=5,  polyorder=2

        3. Retourne le DataFrame enrichi (colonnes ajoutées in-place)
        """
```

**Règles** :
- L'ATR et le Savgol sont calculés **ici et nulle part ailleurs**
- Les détecteurs accèdent à l'ATR local via `df['atr'].iloc[index]`
- Les colonnes `smoothed_high` / `smoothed_low` sont utilisées **uniquement** par `PivotDetector`
- Les données brutes (`high`, `low`, `close`) restent la référence pour le rendu et les prix exacts

## Étape 2 : Detector

**Responsabilité** : analyser le DataFrame et retourner des `PatternResult`.

### Structure de retour commune

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class PatternType(Enum):
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    TRENDLINE_UP = "trendline_up"
    TRENDLINE_DOWN = "trendline_down"
    SUPPORT = "support"
    RESISTANCE = "resistance"
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    HEAD_SHOULDERS = "head_shoulders"
    INV_HEAD_SHOULDERS = "inv_head_shoulders"
    TRIANGLE_ASC = "triangle_asc"
    TRIANGLE_DESC = "triangle_desc"
    FLAG = "flag"
    CONSOLIDATION = "consolidation"

@dataclass
class PatternResult:
    pattern_type: PatternType
    pair: str
    timeframe: str
    timestamp_detected: datetime      # Bougie de détection
    start_index: int                  # Index début du pattern dans le df
    end_index: int                    # Index fin (= bougie de détection)
    confidence: float                 # 0.0 à 1.0
    key_points: list[dict]            # Points clés du pattern
    # Chaque key_point : {"label": str, "index": int, "price": float}
    atr_at_detection: float           # ATR au moment de la détection (pour normaliser/comparer)
    window_start_index: int           # Index début de la fenêtre de contexte (pour le rendu)
    window_end_index: int             # Index fin = current_pivot.index (pour le rendu)
    annotations: dict = field(default_factory=dict)
    # Données supplémentaires selon le type de pattern
    # Ex: {"neckline": 1.0850, "target": 1.0750} pour un ETE
```

**Règle absolue** : chaque sous-module de `detector/` retourne une `list[PatternResult]`. Aucune exception.

### Ordre d'exécution des détecteurs

```
0. pivots.py        → PRÉ-CALCUL BATCH sur tout le DataFrame (une seule fois)
   ↓ retourne un PivotStore indexé
1. levels.py        → Supports & résistances (query pivots par plage d'index)
2. trendlines.py    → Droites de tendance (query pivots par plage d'index)
3. patterns/*.py    → Figures chartistes (query pivots par plage d'index)
```

**Les pivots sont un pré-calcul, pas un détecteur comme les autres.** Ils sont calculés une seule fois sur l'intégralité du DataFrame (toutes les bougies du timeframe), puis stockés dans une structure indexée. Les autres détecteurs récupèrent les pivots nécessaires par plage d'index (ex: `pivots_in_range(start, end)`) sans jamais les recalculer.

### Matrice de dépendances des détecteurs

| Détecteur         | df | pivot_store | levels | trendlines |
|-------------------|:--:|:-----------:|:------:|:----------:|
| levels.py         | ✅ | ✅          | —      | —          |
| trendlines.py     | ✅ | ✅          | —      | —          |
| double.py         | ✅ | ✅          | ❌     | ❌         |
| head_shoulders.py | ✅ | ✅          | ❌     | ❌         |
| triangles.py      | ✅ | ✅          | ❌     | ✅         |
| flag.py           | ✅ | ✅          | ❌     | ✅         |
| consolidation.py  | ✅ | ✅          | ✅     | ❌         |

❌ = non nécessaire, ne pas passer en argument.

### Pré-calcul des pivots (swing highs/lows)

**Les pivots ne suivent PAS le même flow que les autres détecteurs.** Ils sont calculés en batch sur l'ensemble du DataFrame (toutes les bougies du timeframe d'un coup), puis stockés dans une structure indexée réutilisable.

```python
@dataclass
class Pivot:
    index: int              # Index dans le DataFrame source
    timestamp: datetime
    price: float            # high pour swing_high, low pour swing_low
    pivot_type: str         # "swing_high" ou "swing_low"
    strength: int           # 1 (minor), 2 (medium), 3 (major) — nb d'échelles de détection
    prominence: float       # Proéminence en unités de prix (scipy find_peaks)

class PivotDetector:
    """
    Détection multi-échelle des pivots (voir PATTERNS.md §1).

    Utilise 3 échelles (minor/medium/major) et fusionne les résultats.
    La strength d'un pivot = nombre d'échelles où il est détecté.
    Utilise scipy.signal.find_peaks sur les colonnes smoothed_high / smoothed_low.

    Pour les swing lows : inverser le signal → find_peaks(-smoothed_low, ...).
    """

    SCALES = {
        "minor":  {"left": 3,  "right": 3},
        "medium": {"left": 5,  "right": 5},
        "major":  {"left": 10, "right": 10},
    }

    def compute_all(self, df: pd.DataFrame) -> "PivotStore":
        """
        Calcul vectorisé sur TOUT le DataFrame.
        Utilise df['smoothed_high'] et df['smoothed_low'] (colonnes Enricher).
        Retourne un PivotStore (pas une list[PatternResult]).
        Appelé UNE SEULE FOIS par run de pipeline.
        """

class PivotStore:
    """Structure indexée pour accès rapide aux pivots."""
    highs: list[Pivot]  # Triés par index
    lows: list[Pivot]   # Triés par index

    def in_range(self, start: int, end: int, pivot_type: str = "both") -> list[Pivot]:
        """Retourne les pivots entre start et end (index df). Recherche par bisect."""

    def last_n(self, before_index: int, n: int, pivot_type: str = "both") -> list[Pivot]:
        """Retourne les n derniers pivots avant un index donné."""

    def all(self, pivot_type: str = "both") -> list[Pivot]:
        """Retourne tous les pivots (highs + lows), triés par index."""
```

**Pourquoi ce traitement spécial :**
- Les pivots sont une donnée de base réutilisée par TOUS les autres détecteurs
- Les calculer en batch (vectorisé numpy) est ~100x plus rapide que bougie par bougie
- Le `PivotStore` permet un accès O(log n) par plage d'index via bisect
- Les autres détecteurs appellent `pivot_store.in_range(start, end)` pour récupérer les pivots dont ils ont besoin

### Détection des supports/résistances

```python
class LevelDetector:
    """
    Méthode : Kernel Density Estimation (KDE) sur les prix des pivots
    (voir PATTERNS.md §2 pour le détail).

    - KDE calculé sur une fenêtre glissante (paramètre level_lookback_bars),
      PAS sur l'intégralité des données historiques
    - Les pics de densité = niveaux candidats
    - Validation : >= 2 touches, répartition temporelle, réaction du prix
    - Force = scoring multi-critères pondéré (touches, spread, réaction, récence)
    - Classification S/R dynamique selon position du prix actuel (flip S/R possible)
    """
```

### Détection des trendlines

```python
class TrendlineDetector:
    """
    Méthode : RANSAC (Random Sample Consensus) sur les pivots
    (voir PATTERNS.md §3 pour le détail).

    - Connecter les swing lows (trendline haussière) / swing highs (trendline baissière)
    - Candidats : pivots dans une fenêtre glissante (paramètre trendline_lookback_bars),
      PAS toutes les combinaisons sur 20 ans
    - RANSAC avec residual_threshold en multiples d'ATR
    - Validation >= 3 inliers, déduplication des quasi-parallèles
    - Scoring multi-critères pondéré (inliers, durée, précision, récence, respect)
    """
```

## Étape 3 : Renderer

**Responsabilité** : générer une image PNG par `PatternResult`.

```python
class ChartRenderer:
    def render(self, df: pd.DataFrame, result: PatternResult) -> Path:
        """
        1. Extraire la fenêtre de bougies depuis le PatternResult :
           df[result.window_start_index : result.window_end_index + 1]
           → Fenêtre de contexte de context_window_size bougies,
             centrée sur le pivot courant (= bord droit).
        2. Dessiner le chart en chandeliers (mplfinance)
        3. Annoter selon le type de pattern :
           - Marqueurs sur les key_points
           - Lignes de tendance / necklines
           - Zones de support/résistance (rectangles semi-transparents)
        4. Titre : "{pair} {timeframe} - {pattern_type} @ {timestamp}"
        5. Sauvegarder dans : output/{pattern_type.value}/{pair}_{tf}_{timestamp}.png
        6. Retourner le Path du fichier généré
        """
```

**Note** : la fenêtre de rendu est déterminée par la fenêtre de contexte du pivot (stockée dans `window_start_index` / `window_end_index` du `PatternResult`), pas calculée par le renderer.

**Style mplfinance** :
- Type : `candle` (chandeliers japonais)
- Style : `charles` ou custom dark theme
- Dimensions : 1920x1080 pixels (lisibilité)
- Annotations : couleurs distinctes par type (rouge résistance, vert support, bleu trendline)

## Orchestration (pipeline.py)

### Itération par pivots avec fenêtre de contexte

Le pipeline itère sur les **pivots** (pas sur les bougies). Pour chaque pivot `P`, il définit une **fenêtre de contexte** de `context_window_size` bougies (configurable, défaut = 600) en arrière depuis `P.index`. Les détecteurs ne cherchent que les patterns dont **`P` est le dernier élément constitutif** (le pivot qui "complète" le pattern).

**Pourquoi itérer sur les pivots** :
- Les patterns sont définis par des séquences de pivots, pas de bougies. Itérer sur les pivots est la granularité naturelle.
- Le nombre de pivots est très inférieur au nombre de bougies (~quelques milliers vs ~700k en M15). La performance est excellente sans aucune optimisation supplémentaire.
- Chaque pattern n'est détecté **qu'une seule fois** (au moment où son dernier pivot apparaît), donc **aucune déduplication n'est nécessaire**.

**Fenêtre de contexte** : pour un pivot à l'index `i`, la fenêtre est `[max(0, i - context_window_size + 1), i]`. Seuls les pivots dans cette fenêtre sont visibles par les détecteurs. Cela évite de chercher des patterns sur 20 ans de données et donne un contexte visuel cohérent pour le rendu.

```
Exemple avec pivots P1(100), P2(130), P3(160), P4(200), P5(230), window=600 :

Pivot P1 : fenêtre [0, 100]     → détecteurs cherchent : P1 est-il le dernier élément d'un pattern ?
                                    (pas assez de pivots avant → probablement rien)
Pivot P2 : fenêtre [0, 130]     → P2 est un swing low. Dernier élément d'un support ? D'un flag ?
Pivot P3 : fenêtre [0, 160]     → P3 est un swing high. Dernier sommet d'un double top (P1+P2+P3) ? ✅
Pivot P4 : fenêtre [0, 200]     → P4 est un swing low. On ne re-cherche PAS le double top P1+P2+P3.
Pivot P5 : fenêtre [0, 230]     → P5 est un swing high. Dernier sommet d'un nouveau pattern ?
```

### Règle de détection : le pivot courant est le dernier maillon

Chaque détecteur reçoit le **pivot courant** comme point d'ancrage et cherche en arrière dans la fenêtre :

| Détecteur       | Le pivot courant est...                                  |
|-----------------|----------------------------------------------------------|
| double.py       | H2 (le 2ème sommet) ou L2 (le 2ème creux)               |
| head_shoulders  | ED (la 2ème épaule, dernier pivot de la séquence de 5)   |
| triangles.py    | Le dernier pivot qui touche un bord du triangle          |
| flag.py         | Le dernier pivot du canal (drapeau)                      |
| consolidation   | Le dernier pivot dans la zone de range                   |
| trendlines.py   | Le dernier pivot inlier de la trendline                  |
| levels.py       | Le dernier pivot qui touche le niveau S/R                |

Cette contrainte garantit que chaque pattern est détecté **exactement une fois**, au moment précis où sa structure se complète.

### Code du pipeline

```python
class Pipeline:
    def run(self, pair: str, timeframe: str) -> list[Path]:
        # ── Étape 1 : chargement ──
        df = self.loader.load(pair, timeframe)
        logger.info(f"{pair}/{timeframe} loaded: {len(df)} rows")

        # ── Étape 1.5 : enrichissement (ATR, Savgol) ──
        df = self.enricher.enrich(df, timeframe)

        # ── Étape 2.0 : pré-calcul batch des pivots (une seule fois) ──
        pivot_store = self.pivot_detector.compute_all(df)
        all_pivots = pivot_store.all()  # triés par index
        logger.info(
            f"{len(pivot_store.highs)} swing highs, "
            f"{len(pivot_store.lows)} swing lows detected"
        )

        # ── Étape 2.1 : itération sur les pivots ──
        window_size = self.config["context_window_size"]  # ex: 600
        all_results: list[PatternResult] = []

        for current_pivot in all_pivots:
            # Fenêtre de contexte : [current_pivot.index - W + 1, current_pivot.index]
            win_start = max(0, current_pivot.index - window_size + 1)
            win_end = current_pivot.index

            # Pivots disponibles dans la fenêtre (pour les détecteurs)
            context_pivots = pivot_store.in_range(win_start, win_end)

            # Détection : chaque détecteur cherche les patterns dont
            # current_pivot est le DERNIER élément constitutif
            levels = self.level_detector.detect(
                df, pivot_store, current_pivot, win_start, win_end
            )
            trendlines = self.trendline_detector.detect(
                df, pivot_store, current_pivot, win_start, win_end
            )
            patterns = self.pattern_manager.detect_all(
                df, pivot_store, current_pivot, win_start, win_end,
                levels, trendlines
            )

            all_results.extend(levels + trendlines + patterns)

        logger.info(f"{len(all_results)} patterns detected across {len(all_pivots)} pivots")

        # ── Étape 3 : rendu (skip si confidence < seuil) ──
        renderable = [r for r in all_results if r.confidence >= self.config["render_min_confidence"]]
        images = [self.renderer.render(df, r) for r in renderable]
        logger.info(f"{len(images)} images saved — completed {pair}/{timeframe}")
        return images
```

### Signatures des détecteurs

Tous les détecteurs reçoivent le `current_pivot` en plus des bornes de fenêtre :

```python
class LevelDetector:
    def detect(self, df: pd.DataFrame, pivot_store: PivotStore,
               current_pivot: Pivot, win_start: int, win_end: int
               ) -> list[PatternResult]: ...

class TrendlineDetector:
    def detect(self, df: pd.DataFrame, pivot_store: PivotStore,
               current_pivot: Pivot, win_start: int, win_end: int
               ) -> list[PatternResult]: ...
```

Les détecteurs appellent `pivot_store.in_range(win_start, win_end)` pour obtenir les pivots de contexte, puis cherchent des séquences qui se terminent par `current_pivot`.

### PatternDetectorManager

```python
class PatternDetectorManager:
    """Orchestre l'appel à chaque sous-détecteur de patterns/."""

    def detect_all(
        self,
        df: pd.DataFrame,
        pivot_store: PivotStore,
        current_pivot: Pivot,
        win_start: int,
        win_end: int,
        levels: list[PatternResult],
        trendlines: list[PatternResult],
    ) -> list[PatternResult]:
        results = []
        # Patterns qui n'ont besoin que de df + pivot_store
        results += self.double_detector.detect(df, pivot_store, current_pivot, win_start, win_end)
        results += self.hs_detector.detect(df, pivot_store, current_pivot, win_start, win_end)
        # Patterns qui ont besoin des trendlines
        results += self.triangle_detector.detect(
            df, pivot_store, current_pivot, win_start, win_end, trendlines
        )
        results += self.flag_detector.detect(
            df, pivot_store, current_pivot, win_start, win_end, trendlines
        )
        # Patterns qui ont besoin des levels
        results += self.consolidation_detector.detect(
            df, pivot_store, current_pivot, win_start, win_end, levels
        )
        return results
```

### Logging du pipeline

Chaque étape log à `INFO` :
- **Loader** : `"{pair}/{tf} loaded: {n_rows} rows"`
- **Enricher** : `"ATR(14) + Savgol computed (window={w}, polyorder={p})"`
- **PivotDetector** : `"{n_highs} swing highs, {n_lows} swing lows detected"`
- **Itération** : `"{n_patterns} patterns detected across {n_pivots} pivots"`
- **Chaque détecteur** : `"{n} {pattern_type} detected (avg confidence: {avg:.2f})"`
- **Renderer** : `"{n} images saved to output/{pattern_type}/"`
- **Pipeline total** : `"Completed {pair}/{tf} in {elapsed:.1f}s — {n_patterns} patterns, {n_images} images"`

## Gestion multi-timeframe

Le pipeline est exécuté indépendamment pour chaque combinaison `(pair, timeframe)`. Pas de logique cross-timeframe dans la v1. Chaque run est isolé.

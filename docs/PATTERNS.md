# PATTERNS.md — Méthodes robustes de détection des patterns

Ce fichier définit les méthodes de détection pour chaque pattern. L'objectif est la **fiabilité et la robustesse** sur 20 ans de données multi-timeframe, pas la simplicité d'implémentation.

---

## Philosophie générale

### Problème des seuils fixes
Les seuils en pourcentage fixe (ex: "écart < 0.3%") ne fonctionnent PAS sur du multi-timeframe et multi-paire. La volatilité d'EURUSD en H1 n'a rien à voir avec GBPJPY en M15. **Tous les seuils doivent être adaptatifs**, normalisés par la volatilité locale (ATR).

### Normalisation par ATR (Average True Range)
Chaque seuil de distance/prix est exprimé en **multiples d'ATR** plutôt qu'en pourcentage fixe.

**Calcul correct de l'ATR de Wilder (14 périodes)** :
```python
# True Range : prend en compte le gap par rapport au close précédent
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low'] - df['close'].shift(1)).abs()
], axis=1).max(axis=1)

# ATR = EMA du True Range (méthode Wilder)
atr = tr.ewm(span=14, adjust=False).mean()
```

**⚠️ Ne PAS utiliser** `df['high'].rolling(14).max() - df['low'].rolling(14).min()` — c'est le range sur 14 périodes, pas l'ATR. L'ATR de Wilder inclut les gaps (close précédent) et utilise un lissage EMA, ce qui donne des valeurs plus stables et plus faibles.

**Repères de seuils en ATR** :
- Un "écart faible" = < 0.5 × ATR
- Un "mouvement significatif" = > 1.5 × ATR

L'ATR est calculé une fois par l'Enricher (voir ARCHITECTURE.md §1.5) et stocké dans `df['atr']`. Les détecteurs accèdent à l'ATR local via `df['atr'].iloc[index]`.

### Pré-traitement : débruitage multi-échelle
Avant la détection des pivots, appliquer un **filtre de Savitzky-Golay** (`scipy.signal.savgol_filter`) sur les séries high/low pour réduire le bruit haute fréquence tout en préservant la forme des mouvements de prix. Cela réduit drastiquement les faux pivots.

```python
from scipy.signal import savgol_filter

# Paramètres adaptatifs par timeframe :
# M15/M30 : window=11, polyorder=3
# H1/H4   : window=7,  polyorder=3
# D1/W1   : window=5,  polyorder=2
smoothed_high = savgol_filter(df['high'], window_length=11, polyorder=3)
smoothed_low = savgol_filter(df['low'], window_length=11, polyorder=3)
```

**Important** : le Savitzky-Golay est utilisé UNIQUEMENT pour la détection des pivots. Les données brutes (non lissées) restent la référence pour le rendu et les prix exacts. Le lissage est calculé par l'Enricher et stocké dans `df['smoothed_high']` et `df['smoothed_low']`.

### Pipeline de validation en 3 niveaux
Chaque pattern passe par :
1. **Détection géométrique** : les conditions structurelles sont remplies
2. **Validation statistique** : le pattern est significatif vs le bruit ambiant
3. **Scoring multi-critères** : un score composite pondéré, pas un simple compteur additif

### Stratégie de scan
Les détecteurs de patterns ne scannent PAS chaque bougie du DataFrame. Ils **itèrent sur les pivots du PivotStore** et cherchent des séquences de pivots qui matchent la structure géométrique du pattern. Cela réduit drastiquement le nombre d'itérations (de ~700k bougies à quelques milliers de pivots).

### Timing de détection (no lookahead bias)
- La détection à l'index `i` ne doit utiliser que `df[:i+1]`
- **Pattern NON confirmé** : émis dès que la structure géométrique est complète (ex: double top détecté dès que H2 est formé, même sans cassure neckline)
- **Pattern CONFIRMÉ** : émis quand la bougie clôture au-delà du niveau de cassure
- Les deux versions sont émises comme `PatternResult` séparés (avec `annotations["confirmed"]` = `False` / `True`)

### Fenêtres de recherche par pattern

| Pattern          | Min bougies | Max bougies | Min pivots |
|------------------|-------------|-------------|------------|
| Double Top/Bot   | 10          | 150         | 3          |
| ETE              | 20          | 300         | 5          |
| Triangle         | 15          | 200         | 4          |
| Flag             | 25          | 70          | 6          |
| Consolidation    | 20          | 200         | 4          |

### Note d'implémentation : patterns miroirs
Les patterns miroirs (double bottom, ETE inversé, triangle descendant) ne doivent **PAS** être implémentés comme des fonctions séparées. Utiliser une logique unique paramétrée par la direction (`direction: Literal["bullish", "bearish"]`), dans le même module que leur version primaire. Cela évite la duplication de code et garantit la cohérence des critères.

---

## 1. Points hauts / bas (Swing Highs & Lows)

**Module** : `detector/pivots.py`

**⚠️ Pré-calcul batch** sur l'intégralité du DataFrame (voir ARCHITECTURE.md).

### Méthode : détection multi-échelle

Plutôt qu'un seul paramètre `N` pour left/right bars, utiliser **plusieurs échelles de détection** et fusionner les résultats :

```python
class PivotDetector:
    SCALES = {
        "minor":  {"left": 3,  "right": 3},   # Pivots mineurs (bruit)
        "medium": {"left": 5,  "right": 5},   # Pivots standards
        "major":  {"left": 10, "right": 10},   # Pivots majeurs
    }
```

Chaque pivot reçoit un attribut `strength` basé sur :
- Le nombre d'échelles où il est détecté (un pivot détecté à 3 échelles est plus significatif)
- La **proéminence** (`scipy.signal.find_peaks(prominence=...)`) : la différence de prix entre le pivot et le creux le plus proche de chaque côté
- La distance temporelle au pivot suivant/précédent (isolation)

```python
from scipy.signal import find_peaks

# Détection des swing highs avec proéminence
peaks, properties = find_peaks(
    smoothed_high,
    distance=min_distance,        # Distance min entre deux pivots
    prominence=min_prominence,    # Proéminence min en unités de prix
    width=min_width               # Largeur min du pic
)
# properties contient : prominences, left_bases, right_bases, widths

# ⚠️ Détection des swing lows : INVERSER le signal
# find_peaks trouve les maxima → on inverse pour trouver les minima
valleys, valley_props = find_peaks(
    -smoothed_low,                # <— signe négatif !
    distance=min_distance,
    prominence=min_prominence,
    width=min_width
)
# Les indices valleys correspondent aux minima de smoothed_low
```

**Proéminence minimale** : `0.5 × ATR(14)` du timeframe. Cela élimine le bruit naturellement.

### Niveaux de force des pivots

| Strength | Critère |
|----------|---------|
| 1 (minor) | Détecté uniquement à l'échelle minor |
| 2 (medium) | Détecté aux échelles minor + medium |
| 3 (major) | Détecté aux 3 échelles, proéminence > 1.5 × ATR |

Les détecteurs de patterns en aval peuvent filtrer par `min_strength` selon leurs besoins.

---

## 2. Supports & Résistances

**Module** : `detector/levels.py`

### Méthode : Kernel Density Estimation (KDE) sur les prix des pivots

Le clustering simple par seuil fixe est fragile. Utiliser une **estimation par noyau** pour identifier les zones de densité de prix :

```python
from scipy.stats import gaussian_kde

# ⚠️ KDE sur une FENÊTRE GLISSANTE, pas sur l'intégralité des 20 ans
# Paramètre : level_lookback_bars (ex: 1000 bougies par défaut)
recent_pivots = pivot_store.in_range(
    start=max(0, current_index - config["level_lookback_bars"]),
    end=current_index
)
pivot_prices = [p.price for p in recent_pivots]

kde = gaussian_kde(pivot_prices, bw_method='silverman')

# Échantillonner la densité sur une grille fine
price_grid = np.linspace(min(pivot_prices), max(pivot_prices), 1000)
density = kde(price_grid)

# Les pics de densité = niveaux de support/résistance
level_peaks, props = find_peaks(density, prominence=0.1, distance=20)
levels = price_grid[level_peaks]
```

**Pourquoi une fenêtre glissante** : un KDE sur 20 ans de données retournerait des niveaux historiques qui ne sont plus pertinents (ex: un support de 2005 sur EURUSD à 1.20 n'a plus de sens en 2024). Le paramètre `level_lookback_bars` dans `config.py` contrôle cette fenêtre.

### Validation des niveaux

Un niveau brut issu du KDE est validé par :
1. **Nombre de touches** : >= 2 pivots dans la zone (zone = niveau ± 0.3 × ATR)
2. **Répartition temporelle** : les touches ne sont pas toutes groupées (écart-type des timestamps > seuil)
3. **Réaction du prix** : à chaque touche, le prix a rebondi d'au moins 0.5 × ATR dans la direction opposée

### Force d'un niveau

```python
level_strength = (
    0.3 * normalized_touches +       # Nombre de touches (normalisé 0-1)
    0.3 * temporal_spread +           # Répartition dans le temps (normalisé 0-1)
    0.2 * avg_reaction_magnitude +    # Amplitude moyenne des rebonds (en ATR)
    0.2 * recency_factor              # Bonus pour les touches récentes
)
```

### Classification S/R dynamique

Le rôle (support ou résistance) est déterminé par la position du prix actuel par rapport au niveau, et **peut changer** (flip S/R). Le `PatternResult` inclut l'historique des rôles.

---

## 3. Droites de tendance

**Module** : `detector/trendlines.py`

### Méthode : RANSAC (Random Sample Consensus)

La régression linéaire classique (OLS) est très sensible aux outliers. Un seul faux pivot peut fausser toute la droite. **RANSAC** est conçu pour ça :

```python
from sklearn.linear_model import RANSACRegressor

class TrendlineDetector:
    def _fit_trendline(self, pivots: list[Pivot]) -> Optional[Trendline]:
        X = np.array([p.index for p in pivots]).reshape(-1, 1)
        y = np.array([p.price for p in pivots])

        ransac = RANSACRegressor(
            min_samples=2,                    # 2 points min pour une droite
            residual_threshold=0.5 * self.atr,  # Tolérance en ATR
            max_trials=200,
        )
        ransac.fit(X, y)

        inlier_mask = ransac.inlier_mask_
        n_inliers = inlier_mask.sum()

        if n_inliers < 3:
            return None  # Pas assez de points de contact

        slope = ransac.estimator_.coef_[0]
        intercept = ransac.estimator_.intercept_
        return Trendline(slope, intercept, inlier_mask, n_inliers)
```

### Algorithme complet

1. **Candidats** : collecter les pivots de même type dans une **fenêtre glissante** (paramètre `trendline_lookback_bars`, ex: 200 bougies). Ne PAS générer toutes les combinaisons sur 20 ans — c'est explosif (C(n,2) avec n = centaines de pivots). RANSAC se charge de trouver le meilleur fit parmi les candidats de la fenêtre.
2. **Filtrage de pente** : éliminer les pentes aberrantes (> 45° en échelle normalisée ATR)
3. **RANSAC** : fitter chaque groupe de candidats, retenir ceux avec >= 3 inliers
4. **Déduplication** : fusionner les trendlines quasi-parallèles (pente similaire ± 5%, intercept similaire ± 0.3 ATR)
5. **Scoring** :

```python
trendline_score = (
    0.25 * (n_inliers / max_possible_inliers) +     # Ratio de points de contact
    0.25 * duration_score +                           # Durée couverte (en bougies)
    0.20 * (1 - residual_std / self.atr) +           # Précision du fit
    0.15 * recency_score +                            # Dernière touche récente
    0.15 * respect_score                              # Le prix respecte la droite
)
```

### Validation

Une trendline est **active** tant que le prix ne clôture pas au-delà d'elle de plus de 1 × ATR pendant 3 bougies consécutives.

---

## 4. Double Top

**Module** : `detector/patterns/double.py`

### Détection géométrique

1. Trouver deux swing highs (H1, H2) avec `strength >= 2`
2. **Proximité de prix** : `|H1.price - H2.price| < 0.75 × ATR`
3. Un swing low (L) entre H1 et H2 avec `strength >= 1`
4. **Profondeur** : `(mean(H1, H2) - L.price) > 1.0 × ATR`
5. **Espacement** : distance H1→H2 entre 10 et 150 bougies
6. **Symétrie** : ratio `dist(H1,L) / dist(L,H2)` entre 0.33 et 3.0

### Validation statistique

- **Volume** (si disponible) : le volume sur H2 devrait être inférieur à H1 (divergence volume-prix)
- **Momentum** : comparer la pente d'approche vers H1 vs H2. Un H2 atteint avec moins de momentum est plus significatif.
- **Confirmation** : cassure sous L.price (neckline). Le flag `confirmed` distingue les patterns en formation des patterns confirmés.

### Scoring

```python
confidence = (
    0.20 * price_proximity_score +     # Plus H1 ≈ H2, mieux c'est
    0.20 * depth_score +               # Profondeur de la vallée en ATR
    0.15 * symmetry_score +            # Symétrie temporelle du pattern
    0.15 * volume_divergence_score +   # Divergence volume (0 si pas de volume)
    0.15 * momentum_divergence_score + # Momentum décroissant
    0.15 * breakout_quality_score      # Qualité de la cassure (si confirmé)
)
```

**annotations** : `{"neckline": float, "target": float, "confirmed": bool, "h1_price": float, "h2_price": float}`

---

## 5. Double Bottom

**Module** : `detector/patterns/double.py`

Miroir du Double Top, implémenté via le même code avec `direction="bearish"`. Deux swing lows proches, un swing high entre les deux. Mêmes critères inversés, même scoring.

---

## 6. Épaule-Tête-Épaule (ETE)

**Module** : `detector/patterns/head_shoulders.py`

### Détection géométrique

1. Identifier une séquence de 5 pivots alternés : **EG**(high) → **L1**(low) → **T**(high) → **L2**(low) → **ED**(high)
2. `T.price > EG.price` ET `T.price > ED.price` (la tête dépasse)
3. **Proéminence de la tête** : `T.price - max(EG.price, ED.price) > 0.5 × ATR`
4. **Symétrie des épaules** : `|EG.price - ED.price| < 1.0 × ATR`
5. **Espacement** : distance totale EG→ED entre 20 et 300 bougies
6. **Neckline** : droite reliant L1 et L2. Pente acceptable : `|slope| < ATR / (distance L1→L2)`

### Validation statistique

- **Volume** : pattern idéal = volume décroissant sur la séquence EG→T→ED
- **Symétrie temporelle** : `dist(EG,T) / dist(T,ED)` entre 0.4 et 2.5
- **Qualité de la neckline** : une neckline quasi-horizontale est plus fiable
- **Rejet de la tête** : la bougie au sommet de T devrait montrer un rejet (longue mèche haute / doji)

### Scoring

```python
confidence = (
    0.15 * head_prominence_score +      # La tête dépasse bien les épaules
    0.15 * shoulder_symmetry_score +     # EG ≈ ED en prix
    0.15 * temporal_symmetry_score +     # Symétrie temporelle
    0.15 * neckline_quality_score +      # Neckline horizontale
    0.10 * volume_pattern_score +        # Volume décroissant
    0.10 * head_rejection_score +        # Rejet au sommet
    0.10 * depth_score +                 # Profondeur (tête - neckline) en ATR
    0.10 * breakout_quality_score        # Qualité de la cassure neckline
)
```

---

## 7. ETE Inversé

**Module** : `detector/patterns/head_shoulders.py`

Miroir de l'ETE, implémenté via le même code avec `direction="bearish"`. Séquence : low→high→low(tête)→high→low. La tête est le point le plus bas. Cassure au-dessus de la neckline. Mêmes critères inversés.

---

## 8. Triangle Ascendant

**Module** : `detector/patterns/triangles.py`

### Détection géométrique

1. Collecter les pivots dans une fenêtre glissante (derniers 15-200 bougies)
2. **Résistance horizontale** : fitter une droite horizontale (RANSAC) sur les swing highs. Tolérance : résidu < 0.3 × ATR
3. **Support ascendant** : fitter une trendline haussière (RANSAC) sur les swing lows. Pente positive requise.
4. **Convergence** : l'écart entre résistance et support se réduit au fil du temps
5. **Minimum de touches** : >= 2 sur la résistance ET >= 2 sur le support ascendant

### Validation

- **Test de convergence** : calculer le point d'apex (intersection des deux droites). L'apex doit être dans le futur.
- **Ratio de compression** : `(écart début) / (écart fin) > 1.5`
- **Réduction de volatilité** : l'ATR local dans le triangle doit être en déclin

### Scoring

```python
confidence = (
    0.20 * resistance_flatness_score +   # Résistance bien horizontale
    0.20 * support_slope_score +          # Pente haussière claire
    0.15 * convergence_ratio +            # Degré de convergence
    0.15 * touch_count_score +            # Nombre de touches total
    0.15 * volatility_compression +       # Compression de la volatilité
    0.15 * breakout_quality_score         # Qualité cassure (si confirmé)
)
```

---

## 9. Triangle Descendant

**Module** : `detector/patterns/triangles.py`

Miroir du triangle ascendant, implémenté via le même code avec `direction="bearish"`. Support horizontal + résistance descendante. Mêmes critères inversés.

---

## 10. Drapeau (Flag)

**Module** : `detector/patterns/flag.py`

### Détection du mât (pole)

1. Identifier un mouvement impulsif fort : variation de prix > 2 × ATR en < 20 bougies
2. **Pente du mât** : régression linéaire OLS avec R² > 0.85 sur la phase impulsive
3. Le mât doit représenter un mouvement directionnel clair (pas un aller-retour)

**Note** : le mât utilise OLS (pas RANSAC), car c'est un segment court et directionnel où les outliers sont rares. Le R² sert ici à vérifier la qualité directionnelle du mouvement, pas à filtrer des outliers. C'est la seule exception à la règle "RANSAC partout".

### Détection du drapeau (flag body)

1. Après le mât, identifier un canal de consolidation :
   - Fitter deux droites parallèles (RANSAC) sur les swing highs et swing lows du canal
   - **Parallélisme** : écart de pente < 20% entre les deux droites
   - **Contre-tendance** : la pente moyenne du canal est opposée à celle du mât
2. **Amplitude du canal** : < 50% de la hauteur du mât
3. **Durée** : entre 5 et 50 bougies
4. **Pivots internes** : >= 4 pivots alternés dans le canal

### Validation

- **Ratio mât/drapeau** : durée du drapeau < 2× durée du mât
- **Retracement** : le drapeau ne retrace pas plus de 50% du mât
- **Compression de volume** : volume dans le drapeau < volume moyen dans le mât

### Scoring

```python
confidence = (
    0.20 * pole_strength_score +        # Force du mât (amplitude en ATR)
    0.20 * channel_quality_score +       # Qualité du canal (parallélisme, R²)
    0.15 * counter_trend_score +         # Le canal est bien en contre-tendance
    0.15 * retracement_score +           # Retracement limité
    0.15 * duration_ratio_score +        # Ratio durée flag/pole
    0.15 * breakout_quality_score        # Cassure dans le sens du mât
)
```

---

## 11. Consolidation (Range)

**Module** : `detector/patterns/consolidation.py`

### Détection

1. **Fenêtre glissante** : analyser des fenêtres de 20 à 200 bougies
2. **Bornes du range** : identifier le support et la résistance via le KDE local (même méthode que levels.py, avec fenêtre = la fenêtre de consolidation)
3. **Stationnarité** : test ADF (Augmented Dickey-Fuller) sur les closes de la fenêtre. Un range est stationnaire (p-value < 0.05)
4. **Amplitude** : `range_width = resistance - support < consolidation_max_width_atr × ATR` (paramètre configurable dans `config.py`, défaut = 3.0). La valeur par défaut est volontairement large pour couvrir les paires volatiles (GBPJPY) et les timeframes élevés (W1).
5. **Touches** : >= 2 sur le support ET >= 2 sur la résistance
6. **Absence de tendance** : `|slope| < 0.05 × ATR / window_size`

### Validation

- **Containment** : > 80% des closes entre support et résistance
- **Pas de breakout prolongé** : aucune excursion > 1 ATR hors du range pendant > 3 bougies
- **Durée minimale** : >= 20 bougies

### Scoring

```python
confidence = (
    0.25 * containment_ratio +           # % de bougies dans le range
    0.20 * stationarity_score +          # Résultat du test ADF
    0.20 * touch_balance +               # Équilibre touches support/résistance
    0.20 * range_tightness +             # Étroitesse du range (en ATR)
    0.15 * duration_score                # Durée (plus long = plus significatif)
)
```

---

## Dépendances ajoutées au stack

```
scikit-learn     # RANSACRegressor (trendlines, triangles, drapeaux)
scipy            # savgol_filter, find_peaks, gaussian_kde
statsmodels      # adfuller (test de stationnarité pour consolidation)
```

---

## Notes critiques

- **Tous les seuils en ATR** : aucun seuil en % fixe. L'ATR(14) Wilder est la référence universelle. Formule : `EMA(TrueRange, 14)` — voir section "Normalisation par ATR" ci-dessus.
- **ATR calculé par l'Enricher** : une seule fois, stocké dans `df['atr']`. Les détecteurs ne recalculent jamais l'ATR.
- **Savitzky-Golay pour les pivots uniquement** : ne pas lisser les données pour les autres détecteurs. Colonnes `df['smoothed_high']` et `df['smoothed_low']`.
- **RANSAC partout où il y a du fitting linéaire** : trendlines, bords de triangles, canaux de drapeaux. **Exception** : le mât du drapeau utilise OLS (voir §10).
- **Fenêtres glissantes** : les trendlines et les S/R utilisent des fenêtres de lookback configurables (`trendline_lookback_bars`, `level_lookback_bars`), pas l'intégralité des données historiques.
- **find_peaks pour swing lows** : toujours inverser le signal (`-smoothed_low`) avant d'appeler `find_peaks`.
- **Scoring pondéré multi-critères** : chaque pattern a son propre vecteur de poids, configurable via `config.py`.
- **Pas de lookahead bias** : la détection à l'index `i` ne doit utiliser que `df[:i+1]`.
- **`confirmed: bool`** dans les annotations : sépare les patterns en formation des patterns confirmés (post-cassure). Les deux sont émis comme `PatternResult` séparés.
- **Chevauchements acceptés** : un même groupe de bougies peut produire plusieurs patterns. Filtrage par confidence en aval.
- **Patterns miroirs** : implémentés via un paramètre `direction`, pas par duplication de code.
- **Scan par pivots** : les détecteurs itèrent sur les pivots du PivotStore, pas sur chaque bougie.

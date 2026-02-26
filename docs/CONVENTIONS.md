# CONVENTIONS.md — Standards de code & bonnes pratiques

## Style de code

- **Python 3.11+** avec type hints obligatoires sur toutes les fonctions publiques
- **Dataclasses** pour toutes les structures de données (pas de dicts anonymes)
- **Docstrings** : format Google style, obligatoire pour toute classe et méthode publique
- **Nommage** :
  - Fichiers/modules : `snake_case.py`
  - Classes : `PascalCase`
  - Fonctions/variables : `snake_case`
  - Constantes : `UPPER_SNAKE_CASE`
- **Imports** : stdlib → third-party → local, séparés par une ligne vide
- **Pas de `print()`** en production : utiliser `logging` avec niveaux DEBUG/INFO/WARNING

## Gestion des erreurs

- Les fichiers CSV manquants ou corrompus → `FileNotFoundError` ou `ValueError` avec message clair
- Un détecteur qui ne trouve rien retourne une **liste vide**, jamais `None`
- Les erreurs de rendu (ex: pas assez de bougies) → log WARNING + skip, ne pas crasher le pipeline

## Tests

- Framework : **pytest**
- Dossier : `tests/` miroir de `src/`
- Chaque détecteur a un fichier de test avec :
  - Un cas positif (pattern présent → détecté)
  - Un cas négatif (pas de pattern → liste vide)
  - Un cas edge (données insuffisantes → pas de crash)
- Utiliser des DataFrames synthétiques pour les tests (pas besoin de vrais CSV)

## Performance

- Les DataFrames de 20 ans en M15 font ~700k lignes : utiliser des opérations vectorisées numpy/pandas
- Éviter les boucles Python sur les données OHLCV, préférer `rolling()`, `shift()`, slicing numpy
- Le rendering est le bottleneck : ne pas générer d'image si `confidence < 0.5` (seuil configurable)

## Git & fichiers

- `.gitignore` : exclure `data/raw/`, `output/`, `__pycache__/`, `*.pyc`, `.venv/`
- Les CSV de données ne sont PAS versionnés (trop volumineux)
- Les images de sortie ne sont PAS versionnées

## Configuration

Tous les paramètres ajustables centralisés dans un seul fichier ou dict :

```python
# src/config.py
DEFAULT_CONFIG = {
    "pivot_left_bars": 5,
    "pivot_right_bars": 5,
    "level_tolerance_pct": 0.15,
    "level_min_touches": 2,
    "trendline_min_touches": 3,
    "trendline_min_r_squared": 0.85,
    "render_candle_window": 501,
    "render_min_confidence": 0.5,
    "render_dpi": 100,
    "render_figsize": (19.2, 10.8),
	"context_window_size": 600,
}
```

Les détecteurs reçoivent le config en paramètre. Pas de constantes magiques dans le code.

## Nommage des fichiers de sortie

```
output/{pattern_type}/{pair}_{timeframe}_{timestamp_ISO}.png
```
Exemple : `output/double_top/EURUSD_H4_2020-03-15T08-00-00.png`

Les `:` dans les timestamps sont remplacés par `-` pour compatibilité filesystem.

## Tests visuels (validation humaine)
Script dédié : `scripts/visual_check.py`
- Génère N images aléatoires par pattern
- Les place dans `output/visual_check/{pattern}/`
- But : vérifier visuellement que les annotations sont cohérentes
- Ce n'est PAS un test automatisé, c'est un outil de QA humain
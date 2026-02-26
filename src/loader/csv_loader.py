"""CSV loader for OHLCV forex data.

Reads one or more CSV files for a given pair/timeframe, validates columns,
and returns a clean DataFrame indexed by UTC timestamp.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


class CSVLoader:
    """Loads and normalises OHLCV data from CSV files.

    Data must be located at: data/raw/{pair}/{timeframe}/*.csv

    Example:
        loader = CSVLoader()
        df = loader.load("EURUSD", "H4")
    """

    def __init__(self, data_dir: str | Path = "data/raw") -> None:
        """Initialise the loader.

        Args:
            data_dir: Root directory containing raw CSV files.
        """
        self._data_dir = Path(data_dir)

    def load(self, pair: str, timeframe: str) -> pd.DataFrame:
        """Load and normalise OHLCV data for a pair/timeframe.

        Reads all CSV files found in data/raw/{pair}/{timeframe}/, concatenates
        them if multiple files are present, validates columns, converts the
        timestamp column to a UTC DatetimeIndex, removes duplicates, and sorts
        chronologically.

        Args:
            pair: Forex pair identifier (e.g. "EURUSD").
            timeframe: Chart timeframe (e.g. "H4").

        Returns:
            A clean DataFrame with DatetimeIndex (UTC) and columns:
            open, high, low, close, volume.

        Raises:
            FileNotFoundError: If no CSV files are found for the given pair/timeframe.
            ValueError: If required columns are missing in the CSV files.
        """
        # Support two layouts:
        #   1. data/raw/{pair}/{timeframe}/*.csv  (directory with one or more CSVs)
        #   2. data/raw/{pair}/{timeframe}.csv    (single flat file)
        directory = self._data_dir / pair / timeframe
        csv_files = sorted(directory.glob("*.csv")) if directory.is_dir() else []

        if not csv_files:
            flat_file = self._data_dir / pair / f"{timeframe}.csv"
            if flat_file.is_file():
                csv_files = [flat_file]
            else:
                raise FileNotFoundError(
                    f"No CSV data found for {pair}/{timeframe}. "
                    f"Expected: data/raw/{pair}/{timeframe}/*.csv "
                    f"or data/raw/{pair}/{timeframe}.csv"
                )

        frames: list[pd.DataFrame] = []
        for path in csv_files:
            df = pd.read_csv(path)
            self._validate_columns(df, path)
            frames.append(df)

        combined = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

        combined = self._normalise(combined)
        logger.info(
            "%s/%s loaded: %d rows from %d file(s)",
            pair,
            timeframe,
            len(combined),
            len(csv_files),
        )
        return combined

    def _validate_columns(self, df: pd.DataFrame, path: Path) -> None:
        """Ensure required columns are present.

        Args:
            df: DataFrame to validate.
            path: Source file path (for error messages).

        Raises:
            ValueError: If any required column is missing.
        """
        missing = REQUIRED_COLUMNS - set(df.columns.str.lower())
        if missing:
            raise ValueError(
                f"Missing columns {missing} in {path}. "
                f"Required: {REQUIRED_COLUMNS}"
            )
        # Normalise column names to lowercase
        df.columns = df.columns.str.lower()

    def _normalise(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert timestamp, remove duplicates, sort chronologically.

        Args:
            df: Raw concatenated DataFrame.

        Returns:
            Normalised DataFrame with DatetimeIndex (UTC).
        """
        df.columns = df.columns.str.lower()

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]

        # Cast OHLCV columns to float/int for safety
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(float)

        return df

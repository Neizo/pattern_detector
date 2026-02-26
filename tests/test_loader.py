"""Tests for CSVLoader."""

import io
import textwrap
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.loader import CSVLoader


def _make_csv(rows: int = 5) -> str:
    """Generate a minimal valid OHLCV CSV string."""
    lines = ["timestamp,open,high,low,close,volume"]
    for i in range(rows):
        ts = f"2020-01-{i + 1:02d}T00:00:00Z"
        lines.append(f"{ts},1.1000,1.1050,1.0950,1.1020,{(i + 1) * 100}")
    return "\n".join(lines)


@pytest.fixture()
def csv_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with one CSV file."""
    pair_dir = tmp_path / "EURUSD" / "H4"
    pair_dir.mkdir(parents=True)
    (pair_dir / "data.csv").write_text(_make_csv(10))
    return tmp_path


def test_load_returns_dataframe(csv_dir: Path) -> None:
    """CSVLoader.load returns a non-empty DataFrame with correct columns."""
    loader = CSVLoader(data_dir=csv_dir)
    df = loader.load("EURUSD", "H4")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 10
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df.columns


def test_load_raises_for_missing_directory() -> None:
    """CSVLoader.load raises FileNotFoundError for a non-existent pair/tf."""
    loader = CSVLoader(data_dir="/nonexistent/path")
    with pytest.raises(FileNotFoundError):
        loader.load("EURUSD", "H4")


def test_load_deduplicates_and_sorts(tmp_path: Path) -> None:
    """CSVLoader removes duplicate timestamps and sorts chronologically."""
    csv_content = textwrap.dedent("""\
        timestamp,open,high,low,close,volume
        2020-01-03T00:00:00Z,1.10,1.11,1.09,1.105,300
        2020-01-01T00:00:00Z,1.10,1.11,1.09,1.105,100
        2020-01-02T00:00:00Z,1.10,1.11,1.09,1.105,200
        2020-01-01T00:00:00Z,1.10,1.11,1.09,1.105,100
    """)
    pair_dir = tmp_path / "EURUSD" / "H4"
    pair_dir.mkdir(parents=True)
    (pair_dir / "data.csv").write_text(csv_content)

    loader = CSVLoader(data_dir=tmp_path)
    df = loader.load("EURUSD", "H4")

    assert len(df) == 3
    assert df.index.is_monotonic_increasing

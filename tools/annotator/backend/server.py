"""FastAPI server for the annotation tool."""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

# Setup path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.data_provider import DataProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Pattern Detector — Annotation Tool")
provider = DataProvider()

ANNOTATIONS_DIR = PROJECT_ROOT / "annotations"
ANNOTATIONS_DIR.mkdir(exist_ok=True)


# ── API Endpoints ──────────────────────────────────────────────────────────


@app.get("/api/pairs")
def get_pairs():
    """Return available pairs and their timeframes."""
    return {"pairs": provider.get_available_pairs()}


@app.get("/api/candles")
def get_candles(
    pair: str = Query(..., description="Forex pair, e.g. EURUSD"),
    timeframe: str = Query(..., description="Timeframe, e.g. H4"),
    last_n: int = Query(500, ge=10, le=5000),
    before: Optional[str] = Query(None, description="ISO date cutoff"),
):
    """Return OHLCV candles for a pair/timeframe window."""
    try:
        candles = provider.get_candles(pair, timeframe, last_n, before)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    return {
        "pair": pair,
        "timeframe": timeframe,
        "candles": candles,
    }


@app.post("/api/annotations")
async def save_annotations(payload: dict):
    """Save human annotations to JSON file."""
    pair = payload.get("pair", "UNKNOWN")
    tf = payload.get("timeframe", "UNKNOWN")
    filename = f"{pair}_{tf}_human.json"
    path = ANNOTATIONS_DIR / filename

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info("Annotations saved to %s", path)
    return {"status": "saved", "path": str(path)}


@app.get("/api/annotations")
def load_annotations(
    pair: str = Query(...),
    timeframe: str = Query(...),
):
    """Load previously saved annotations."""
    filename = f"{pair}_{timeframe}_human.json"
    path = ANNOTATIONS_DIR / filename

    if not path.is_file():
        return {"annotations": None}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


# ── Static files (frontend) ───────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

MIME_TYPES = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".html": "text/html",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


@app.get("/")
def serve_index():
    """Serve the SPA index.html."""
    return FileResponse(FRONTEND_DIR / "index.html", media_type="text/html")


@app.get("/{filename:path}")
def serve_static(filename: str):
    """Serve frontend static files (JS, CSS, etc.)."""
    filepath = FRONTEND_DIR / filename
    if filepath.is_file() and FRONTEND_DIR in filepath.resolve().parents:
        media_type = MIME_TYPES.get(filepath.suffix, "application/octet-stream")
        return FileResponse(filepath, media_type=media_type)
    return JSONResponse(status_code=404, content={"error": "Not found"})


# ── Entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "backend.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent)],
    )

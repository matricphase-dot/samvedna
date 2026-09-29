# Vercel Python entrypoint: expose the FastAPI app as a serverless function.
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VERCEL", "1")

from app.main import app  # noqa: E402  (Vercel picks up this ASGI app)

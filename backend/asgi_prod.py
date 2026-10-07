"""Production entrypoint: one process, one origin.

  /api/*  -> the FastAPI app (the same app, mounted so the '/api' prefix is stripped, like Vite's dev proxy)
  /*      -> the built React app (frontend/dist)

Run (from backend/):  uvicorn asgi_prod:app --host 0.0.0.0 --port 8000
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.main import app as api

DIST = Path(os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parent.parent / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Starlette does not run a mounted sub-app's lifespan, and ours starts the MCP subprocess + embedding model.
    async with api.router.lifespan_context(api):
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
async def healthz():
    """Cheap liveness probe for the platform (does not touch the database; /api/health does)."""
    return {"status": "ok"}


app.mount("/api", api)
app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")

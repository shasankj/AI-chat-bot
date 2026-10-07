# syntax=docker/dockerfile:1

# ---- stage 1: build the React app -------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: API + static files ----------------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
COPY --from=frontend /frontend/dist frontend/dist

# Bake the embedding model in (~210 MB) so startup never waits on a download.
WORKDIR /app/backend
RUN python -c "from app.rag.embeddings import CACHE_DIR, MODEL_NAME; \
from fastembed import TextEmbedding; TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR))"

# Run as a non-root user. The app and the MCP child process only need read access (plus the model cache).
RUN useradd --system --no-create-home app && chown -R app /app/backend/.model_cache
USER app

EXPOSE 8000
# ONE worker: conversation memory and rate limits live in process memory.
CMD ["uvicorn", "asgi_prod:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

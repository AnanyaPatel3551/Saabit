# Stage 1: build the React app into static files.
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime that serves the API and the built frontend.
FROM python:3.11-slim
# MALLOC_ARENA_MAX stops glibc keeping a separate heap per worker thread, which matters
# with a 512 MB limit. (The Arrow memory pool is set in app/core/ingest.py.)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    PORT=8000
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY data/sample/amazon_sale_report.csv.gz data/sample/amazon_sale_report.csv.gz
COPY data/sample_shopify/shopify_synthetic.csv data/sample_shopify/shopify_synthetic.csv
# Read-only results for the "How we test" page (written by eval.py, score_baseline.py, tasks.ps1)
COPY eval/results/ eval/results/
WORKDIR /app/backend
# Scan the sample now so the running app only reads a small metadata.json.
RUN python -m app.prepare_sample
COPY --from=frontend /app/frontend/dist /app/frontend/dist
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
# No uvicorn access log: it prints full URLs, and ?question= can carry a question. Saabit
# writes its own JSON line per request instead (app/api/observe.py).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]

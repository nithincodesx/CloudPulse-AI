# CloudPulse AI — FastAPI backend image
#
# Builds the backend as a small, non-root image. The same image serves local
# docker-compose dev and the Render free-tier deployment; the CMD honors the
# $PORT Render injects (defaults to 8000 locally).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (cached layer — rebuilds are fast when
# requirements.txt is unchanged).
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application source. .dockerignore keeps .venv/.env/tests out of the image.
COPY . .

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Render injects $PORT; fall back to 8000 for local docker-compose.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]

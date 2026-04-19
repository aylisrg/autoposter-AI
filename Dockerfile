FROM python:3.12-slim AS backend

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps: Pillow needs libjpeg / zlib headers at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/README.md* /app/backend/
RUN pip install --upgrade pip && pip install -e "/app/backend"

COPY backend /app/backend
WORKDIR /app/backend

ENV PYTHONPATH=/app/backend
EXPOSE 8787

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]

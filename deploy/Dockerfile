# NODIQ-X — multi-stage build: API + frontend built in-image
#
# Stage 1 (frontend): builds the Vite SPA. Render passes service env vars to
# `docker build` as build args, so the VITE_FIREBASE_* vars declared below are
# injected at build time (Vite inlines import.meta.env into the bundle).
#
# Stage 2 (runtime): python:3.11-slim with the validated analysis pipeline and
# gunicorn serving both /api and the built SPA (same-origin).

# ---------------------------------------------------------------------------
# Stage 1 — frontend build
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /web

# Build-time public config (Firebase Web keys are public client identifiers).
# Declared as ARG so `docker build --build-arg` / Render env vars reach Vite.
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_STORAGE_BUCKET
ARG VITE_FIREBASE_MESSAGING_SENDER_ID
ARG VITE_FIREBASE_APP_ID
ENV VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY \
    VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN \
    VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID \
    VITE_FIREBASE_STORAGE_BUCKET=$VITE_FIREBASE_STORAGE_BUCKET \
    VITE_FIREBASE_MESSAGING_SENDER_ID=$VITE_FIREBASE_MESSAGING_SENDER_ID \
    VITE_FIREBASE_APP_ID=$VITE_FIREBASE_APP_ID

# NOTE: `npm ci` fails on Linux (EBADPLATFORM on
# @rolldown/binding-win32-x64-msvc) because package-lock.json was
# generated on Windows and pins the Windows-only native binary.
# `npm install --force` skips the platform check. To switch to `npm ci`,
# regenerate the lockfile on Linux (or with --os=linux --cpu=x64
# --libc=musl) in a separate change.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm install --force

COPY apps/web/ ./
# dataset/ is heavy public data served by the BACKEND (server.py), not part
# of the SPA bundle — exclude it from the frontend build context copy.
RUN rm -rf public/dataset && npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Base Python runtime (API + pipeline + static SPA)
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

WORKDIR /app

# System deps for opencv (libgl) — slim images need it for cv2 import
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 python3-tk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application source code, config, and third-party dependencies
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY third_party ./third_party
RUN pip install --no-cache-dir --no-deps -e .

# Frontend bundle from stage 1 (index.html + hashed assets, SPA-served)
COPY --from=frontend /web/dist ./apps/web/dist

# Reference data: the 1000-image sample dataset (dataset browser + demo
# uploads) and the validated-run summary CSV (count accuracy lookups).
COPY apps/web/public/dataset ./apps/web/public/dataset
COPY data/samples ./data/samples

# Persistent state lives here — mount a volume for it
VOLUME ["/app/server_data"]

EXPOSE 8001

ENV PYTHONUNBUFFERED=1 \
    NODIQ_DATA_DIR=/app/server_data \
    CELLPOSE_LOCAL_MODELS_PATH=/app/models

# Production WSGI server. Worker count is env-driven: the default (1 worker
# + 4 threads) fits the 512MB free-tier container — 2 workers OOM-killed
# the container on the first real analysis. On paid tiers set
# GUNICORN_WORKERS=2 (runtime env change, no rebuild needed).
RUN pip install --no-cache-dir gunicorn==23.0.0
CMD ["sh", "-c", "exec gunicorn -w ${GUNICORN_WORKERS:-1} --threads ${GUNICORN_THREADS:-4} -t 120 -b 0.0.0.0:8001 nodiq.api.server:app"]

# ---------------------------------------------------------------------------
# Stage 3 — Target with-astm (optional: full runtime with dedicated ASTM env)
# Build with: docker build --target with-astm -t nodiq-x:astm .
# ---------------------------------------------------------------------------
FROM base AS with-astm
# Create dedicated, isolated ASTM Python virtual environment
# Uses CPU-only PyTorch and torchvision to minimize image size and avoid CUDA driver overhead
RUN python -m venv /opt/venv-astm && \
    /opt/venv-astm/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv-astm/bin/pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    /opt/venv-astm/bin/pip install --no-cache-dir cellpose packaging scipy scikit-image pandas opencv-python-headless
# pandas: module-level dependency of the estimator's 4_evaluate_jeffries.py
# (the Jeffries planimetric runner executes there when the app interpreter's
# pandas is unusable). opencv: writes the binary mask for that runner.
ENV NODIQ_ASTM_PYTHON=/opt/venv-astm/bin/python \
    CELLPOSE_LOCAL_MODELS_PATH=/app/models
# Volume for mounting pre-cached model weights (e.g. cpsam or custom .pt)
VOLUME ["/app/models"]

# ---------------------------------------------------------------------------
# Stage 4 — Target standard (default: fast build, fits 512MB free tiers)
# Build with: docker build -t nodiq-x . (or --target standard)
# ---------------------------------------------------------------------------
FROM base AS standard

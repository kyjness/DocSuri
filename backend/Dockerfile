# Deploy unit ① — API modular monolith (U2/U3/U4/U6-mw).
# SEC-10: base image pinned by sha256 digest. Update hash when upgrading.
FROM python:3.11.9-slim-bookworm@sha256:2856e6af199e8128161abd320575eb9b341f3b76f017b5d0c9cd364f60d8a050

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 docsuri

# Copy shared contracts (docsuri_shared) + ops (docsuri_ops — real grounding hook) + discovery
# (docsuri_discovery) + backend app-shell with in-tree modules (accounts, library).
COPY shared/python /app/shared/python
COPY ops /app/ops
COPY backend/modules/discovery /app/discovery
COPY backend /app/backend

# Install: shared → ops → discovery → backend deps (no backend package itself — PYTHONPATH).
RUN python -m pip install --upgrade pip==24.2 \
    && python -m pip install /app/shared/python /app/ops "/app/discovery[real]" \
    && python -m pip install -r /app/backend/requirements-deploy.txt

USER docsuri

# PYTHONPATH = /app so `backend.*` and top-level `discovery` resolve. Port 8000.
ENV PYTHONPATH=/app
EXPOSE 8000
ENTRYPOINT ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# SEC-10: pinned by digest — update hash when upgrading the base image.
FROM python:3.11.9-slim-bookworm@sha256:2856e6af199e8128161abd320575eb9b341f3b76f017b5d0c9cd364f60d8a050

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 docsuri

COPY shared/python /app/shared/python
COPY ingestion /app/ingestion

RUN python -m pip install --upgrade pip==24.2 \
    && python -m pip install /app/shared/python "/app/ingestion[assets]" \
    && python -m pip install --upgrade boto3 botocore  # AWS changed cohere.embed-multilingual-v3 on-demand request handling ~2026-07; pinned boto3 built a now-rejected request ("invalid model identifier") — force latest SDK

USER docsuri

ENTRYPOINT ["python", "-m", "docsuri_ingestion.worker"]

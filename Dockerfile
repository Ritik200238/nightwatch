# Nightwatch API + recorder image. One image, two commands (see compose.yaml).
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    NIGHTWATCH_DATA_DIR=/data
WORKDIR /app

# Dependencies first so code changes do not invalidate the layer.
COPY pyproject.toml README.md ./
COPY nightwatch ./nightwatch
# Install, then delete the source: with WORKDIR on sys.path, leaving it behind means two
# importable copies of the package and a partial build can leave them disagreeing.
RUN pip install --upgrade pip && pip install ".[api]" && rm -rf /app/nightwatch /app/pyproject.toml

# Non-root runtime user; /data is a volume owned by it.
RUN useradd --create-home --uid 10001 nightwatch && mkdir -p /data && chown nightwatch:nightwatch /data
USER nightwatch
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8).status==200 else 1)" || exit 1

CMD ["uvicorn", "nightwatch.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

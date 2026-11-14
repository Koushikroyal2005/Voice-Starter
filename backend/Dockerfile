# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm AS worker
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH HF_HOME=/home/voice/.cache/huggingface
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra mcp --extra telemetry
RUN useradd --create-home --uid 10001 voice
COPY --chown=voice:voice app ./app
COPY --from=contracts --chown=voice:voice /voice-workbench/v1 /contracts/voice-workbench/v1
COPY --chown=voice:voice alembic.ini mcp.demo.example.json mcp.external.example.json ./
USER voice
# Model assets only; this command explicitly bypasses credential validation.
RUN python -m app.main download-files
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/', timeout=3)"
CMD ["python", "-m", "app.main", "start"]

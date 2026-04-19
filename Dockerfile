FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PORT=8080 TIMEOUT=300 WORKERS=1 LOG_LEVEL=info

# git is required to install alex_leontiev_toolbox_python from GitHub
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY agent_langgraph_taskmaster.py .
COPY utils.py .
COPY slack_taskmaster_server.py .
# _system_message_taskmaster.jinja.md is the symlink resolved by deploy.sh before build
COPY _system_message_taskmaster.jinja.md system_message_taskmaster.jinja.md

RUN mkdir -p .logs

ENV PATH="/app/.venv/bin:$PATH"

CMD exec gunicorn slack_taskmaster_server:app \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --timeout "${TIMEOUT}" \
    --log-level "${LOG_LEVEL}"

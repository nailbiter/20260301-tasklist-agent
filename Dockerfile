FROM python:3.10-slim

WORKDIR /app

ENV PORT=8080 TIMEOUT=120 WORKERS=1 LOG_LEVEL=info

# git is required to pip-install alex_leontiev_toolbox_python from GitHub
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_langgraph_taskmaster.py .
COPY slack_taskmaster_server.py .
# _system_message_taskmaster.jinja.md is the symlink resolved by deploy.sh before build
COPY _system_message_taskmaster.jinja.md system_message_taskmaster.jinja.md

RUN mkdir -p .logs

CMD exec gunicorn slack_taskmaster_server:app \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --timeout "${TIMEOUT}" \
    --log-level "${LOG_LEVEL}"

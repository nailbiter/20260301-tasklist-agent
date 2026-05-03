# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A CLI + Slack LLM agent powered by Google Gemini (`gemini-2.5-flash-lite`) that aggregates and manages tasks from Jira and MongoDB. The primary production path is a **LangGraph**-based graph (`agent_langgraph_taskmaster.py`) consumed by both `cli.py` (local interactive use) and `slack_taskmaster_server.py` (Cloud Run deployment).

## Running the Agents

```bash
# Primary CLI (interactive REPL, human-in-the-loop, SQLite checkpointer)
python cli.py                          # interactive REPL
python cli.py "What are my tasks?"    # single-shot
python cli.py --resume <session-id>   # resume session
python cli.py --list-sessions         # list saved sessions

# LangGraph Studio dev server (uses langgraph.json)
uv run langgraph dev

# Legacy direct-Gemini agents (no session persistence)
python agent_taskmaster.py
python agent_mailmaster.py            # requires Firestore; accepts prompt + session_id via argv

# Utility
python list-sprints.py
```

## Dependency Management

This project uses `uv`, not `pip` directly:

```bash
uv sync            # install from uv.lock
uv add <package>   # add dependency
```

## Code Style

```bash
black .
isort .
```

## Architecture

### LangGraph Graph (`agent_langgraph_taskmaster.py`)

The core graph with three nodes:

- **`agent`** — calls Gemini via `langchain_google_genai.ChatGoogleGenerativeAI` with tools bound.
- **`action`** — executes write tools (`mark_task_done`, `postpone_task`); always preceded by a human-in-the-loop interrupt.
- **`read_action`** — executes read tools (`get_mongo_tasks`) without interruption.

`should_continue` routes: if the last AI message contains write tool calls → `"action"` (interrupt), read tool calls → `"read_action"`, no calls → `END`.

Tools available to the graph:
- `get_mongo_tasks` — queries the `tasks` collection with optional date filters; resolves tag UUIDs to names.
- `mark_task_done` — sets `status = "DONE"` by UUID.
- `postpone_task` — updates `scheduled_date`; accepts UUID prefix.

The system prompt is rendered from `system_message_taskmaster.jinja.md` (a symlink to a private repo) via Jinja2 with today's date injected.

### `cli.py`

Click CLI over the LangGraph graph. Persists state in `state.sqlite` via `SqliteSaver`. Implements the human-in-the-loop loop: after each stream, checks `snapshot.next`; if interrupted, prompts the user for `confirm`/`cancel` before resuming.

### `slack_taskmaster_server.py`

Flask server deployed to Cloud Run. Uses `FirestoreSaver` as the LangGraph checkpointer instead of SQLite. Session IDs are mapped per Slack `user_id` in a MongoDB `logistics/20260321-agent-firestore-sessions` collection. Human-in-the-loop works via Slack messages: agent sends "About to call: …\nReply *confirm* to proceed", user replies "confirm" or "reject".

Slack commands: `reset` / `confirm` / `reject`.

Two routes: `POST /` (Slack Events API) and `POST /slack/ingress` (also accepts slash-command form-encoded requests).

### `agent_mailmaster.py`

Older single-file agent using the `google-genai` SDK directly (not LangGraph). Persists chat history in Firestore `mail_sessions`. Tools: `read_recent_emails`, `mark_as_read`, `label_emails` (Gmail IMAP).

## Deployment

```bash
chmod +x deploy.sh
./deploy.sh    # deploys slack_taskmaster_server.py to Cloud Run (us-east1)
```

`deploy.sh` resolves the `system_message_taskmaster.jinja.md` symlink before the Docker build (the Dockerfile cannot follow symlinks from outside the build context).

## Configuration (`.env`)

```env
GEMINI_API_KEY=...
GENAI_GOOGLE_CLOUD_PROJECT=...
GOOGLE_CLOUD_PROJECT=...

JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=...
JIRA_API_TOKEN=...
JIRA_BOARD_ID=...

MONGO_URI=...
MONGO_DB_NAME=gstasks        # optional, defaults to gstasks
FOR_METADATA_MONGO_URI=...   # separate cluster for session metadata (Slack server)

IMAP_SERVER=imap.gmail.com
EMAIL_USER=...
EMAIL_PASSWORD=...

SLACK_SIGNING_SECRET=...
SLACK_BOT_TOKEN=xoxb-...
TARGET_CHANNEL_ID=...
SERVICE_NAME=...
PROJECT_ID=...
```

## Logging

Use `utils.get_configured_logger` (or `common/logging.py` for shared modules). It sets up a stderr handler plus optional file handler (text + JSON side-by-side). Pass `log_to_file=` to get persistent logs; `file_mode="a"` for append (e.g. the conversation log).

## Adding New Tools

1. Define the function decorated with `@tool` (LangGraph path) in `agent_langgraph_taskmaster.py`.
2. Add to the `tools` list near the top of the file.
3. Register in `action_node` (write tools) or let `read_action` handle it.
4. Update `should_continue` if the routing logic needs to change.

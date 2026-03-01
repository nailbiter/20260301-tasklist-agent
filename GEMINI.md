# Project Overview: CLI Task Agent

This project is a command-line LLM agent powered by Google Gemini (specifically `gemini-2.5-flash-lite`) designed to aggregate and manage tasks from two primary sources: **Jira** (Atlassian) and a **custom MongoDB** database. It provides a unified interface for a user to query their daily priorities, work tasks, and personal to-dos.

## Core Technologies
- **Language:** Python 3.10+
- **LLM SDK:** `google-genai` (v0.3.0+)
- **Integrations:**
    - **Jira:** via `requests` and the `jira` Python library.
    - **MongoDB:** via `pymongo`.
- **Environment Management:** `python-dotenv`.
- **Formatting:** `black` and `isort`.

## Project Structure
- `agent.py`: The main entry point. It initializes the Gemini client, defines the tool-calling functions (`get_jira_tasks`, `get_mongo_tasks`), and handles the conversation loop.
- `list-sprints.py`: A utility script to list active and future sprints from the configured Jira board.
- `utils.py`: Contains shared utility functions, notably a customized logging setup.
- `system_message.md`: Defines the "persona" and core directives for the Gemini agent.
- `pyproject.toml`: Configuration for development tools like `isort` and `black`.
- `requirements.txt`: Lists Python dependencies.

---

## Building and Running

### Prerequisites
Ensure you have Python 3.10+ installed and a virtual environment active.

### Installation
```bash
pip install -r requirements.txt
```

### Configuration
Create a `.env` file in the root directory with the following variables:
```env
GEMINI_API_KEY=your_gemini_api_key
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your_jira_api_token
JIRA_BOARD_ID=your_board_id
MONGO_URI=your_mongodb_connection_string
MONGO_DB_NAME=gstasks (optional, defaults to gstasks)
```

### Running the Agent
To start the agent and ask a query (default is "What are my most important tasks today?"):
```bash
python agent.py
```

### Listing Jira Sprints
To see active and future sprints:
```bash
python list-sprints.py
```

---

## Development Conventions

- **Code Style:** The project follows `black` formatting and `isort` for import sorting.
- **Logging:** Use `utils.get_configured_logger` for consistent logging across the application.
- **Tool Calling:** When adding new capabilities, define them as functions in `agent.py` and include them in the `tools` list passed to `types.GenerateContentConfig`. Ensure they have clear docstrings as these are used by Gemini to understand the tool.
- **System Instructions:** Any changes to the agent's behavior, tone, or high-level logic should be made in `system_message.md`.

# Project Overview: CLI Task Agent

This project is a command-line LLM agent powered by Google Gemini (specifically `gemini-2.5-flash-lite`) designed to aggregate and manage tasks from various sources: **Jira**, a **custom MongoDB** database, and **Mailbox (IMAP)**. It provides a unified interface for a user to query their daily priorities, work tasks, personal to-dos, and emails.

## Core Technologies
- **Language:** Python 3.10+
- **LLM SDK:** `google-genai` (v0.3.0+)
- **Integrations:**
    - **Jira:** via `requests` and the `jira` Python library.
    - **MongoDB:** via `pymongo`.
    - **Email:** via standard `imaplib`.
- **Environment Management:** `python-dotenv`.
- **Formatting:** `black` and `isort`.

## Project Structure
- `agent-taskmaster.py`: The main entry point for tasks. It initializes the Gemini client, defines tool-calling functions for Jira and MongoDB, and handles the conversation loop.
- `agent-mailmaster.py`: The entry point for email management. It provides tools to read recent emails, mark them as read, and label them (Gmail-specific).
- `list-sprints.py`: A utility script to list active and future sprints from the configured Jira board.
- `utils.py`: Contains shared utility functions, notably a customized logging setup.
- `system_message.md`: Defines the "persona" and core directives for the Taskmaster agent.
- `system_message_mail.md`: Defines the "persona" and core directives for the Mailmaster agent.
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
# Gemini API
GEMINI_API_KEY=your_gemini_api_key

# Jira Integration
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your_jira_api_token
JIRA_BOARD_ID=your_board_id

# MongoDB Integration
MONGO_URI=your_mongodb_connection_string
MONGO_DB_NAME=gstasks (optional, defaults to gstasks)

# Email Integration (IMAP)
IMAP_SERVER=imap.gmail.com
EMAIL_USER=your-email@example.com
EMAIL_PASSWORD=your_app_password
```

### Running the Agents

#### Taskmaster
To start the task agent and ask a query:
```bash
python agent-taskmaster.py
```

#### Mailmaster
To start the email agent and ask a query:
```bash
python agent-mailmaster.py
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
- **Tool Calling:** When adding new capabilities, define them as functions in the respective agent script and include them in the `tools` list passed to `types.GenerateContentConfig`. Ensure they have clear docstrings as these are used by Gemini to understand the tool.
- **System Instructions:** Any changes to the agent's behavior, tone, or high-level logic should be made in the corresponding `system_message*.md` file.

## Slack Integration

```markdown
## Slack Integration (Middleware)

The project includes a serverless middleware to funnel Slack messages from a specific channel into the automation pipeline.

### Architecture
- **Trigger:** Slack Events API (specifically `message.channels`).
- **Hosting:** Google Cloud Run (`us-east1`).
- **Security:** HMAC SHA256 signature verification via `X-Slack-Signature`.
- **Filtering:** The middleware only processes messages from a specific `TARGET_CHANNEL_ID` and ignores bot users to prevent infinite loops.

### Components
- `main.py`: A Flask-based entry point that handles the Slack "challenge" handshake, verifies request authenticity, and executes logic based on message content.
- `deploy.sh`: A shell script to deploy the service to Cloud Run with the necessary environment variables.
- `Dockerfile`: Containerizes the Flask app using `gunicorn` for production-grade concurrency.

### Configuration (Add to .env)
```env
# Slack Integration
SLACK_SIGNING_SECRET=your_signing_secret
SLACK_BOT_TOKEN=xoxb-your-bot-token
TARGET_CHANNEL_ID=C0123ABC456
PORT=8080
```

### Deployment
```bash
chmod +x deploy.sh
./deploy.sh
```
```

---

### Pro-tip for your CLI Agent:
Since you are using `gemini-2.5-flash-lite`, it will be very efficient at parsing this documentation. When you start the next session, you can simply say: 

> "I've added a Slack Middleware section to GEMINI.md. We currently have a basic 'echo' logic in `main.py`. I want to connect this middleware to my existing Taskmaster tools."

Is there anything else you'd like to adjust in the project structure before you switch over to the CLI?

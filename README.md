# CLI Task Agent

A command-line LLM agent powered by Gemini that aggregates and answers questions about tasks stored in Jira and a custom MongoDB.

## Prerequisites

* Python 3.10+
* `google-genai` SDK
* `python-dotenv`
* `pymongo` (for database access)
* `requests` or `jira` (for Jira access)

## Setup

1. **Install dependencies:**
```bash
pip install google-genai python-dotenv pymongo requests
```

## TODO

### tasklist agent

#### first-priority

1. CLI
   * more debug info for action
   * batch processing
2. SLACK

#### second-priority

1. memory (via mongo; ask for options)

#### third-priority

1. tool: add tag to a task




import os
import datetime
import json
import requests
from requests.auth import HTTPBasicAuth
from pymongo import MongoClient, DESCENDING
import uuid
from google.cloud import firestore
from dotenv import load_dotenv
from google import genai
from google.genai import types
from utils import get_configured_logger
import typing

# Load environment variables
load_dotenv()

# Initialize Firestore
db = firestore.Client()

LOG_FILE = f""".logs/{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}.log.txt"""

# ---------------------------------------------------------------------------
# Session Management (Firestore)
# ---------------------------------------------------------------------------


def load_chat_history(session_id: str) -> list:
    """Loads the conversation history for a given session from Firestore."""
    # Prefix the session_id to avoid collisions if necessary,
    # but we are already using a separate collection.
    doc_ref = db.collection("task_sessions").document(session_id)
    doc = doc_ref.get()
    if doc.exists:
        # Firestore returns dicts, we need to convert them back to types.Content
        history_data = doc.to_dict().get("history", [])
        contents = []
        for content_dict in history_data:
            parts = []
            for part_dict in content_dict.get("parts", []):
                if "text" in part_dict:
                    parts.append(types.Part.from_text(text=part_dict["text"]))
                elif "function_call" in part_dict:
                    fc = part_dict["function_call"]
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=fc["name"], args=fc["args"]
                            )
                        )
                    )
                elif "function_response" in part_dict:
                    fr = part_dict["function_response"]
                    parts.append(
                        types.Part.from_function_response(
                            name=fr["name"], response=fr["response"]
                        )
                    )
            contents.append(types.Content(role=content_dict["role"], parts=parts))
        return contents
    return []


def save_chat_history(session_id: str, contents: list):
    """Saves the conversation history to Firestore."""
    history_data = []
    for content in contents:
        parts_data = []
        for part in content.parts:
            if part.text:
                parts_data.append({"text": part.text})
            elif part.function_call:
                parts_data.append(
                    {
                        "function_call": {
                            "name": part.function_call.name,
                            "args": part.function_call.args,
                        }
                    }
                )
            elif part.function_response:
                parts_data.append(
                    {
                        "function_response": {
                            "name": part.function_response.name,
                            "response": part.function_response.response,
                        }
                    }
                )
        history_data.append({"role": content.role, "parts": parts_data})

    doc_ref = db.collection("task_sessions").document(session_id)
    doc_ref.set({"history": history_data, "updated_at": firestore.SERVER_TIMESTAMP})


# ---------------------------------------------------------------------------
# Tool Definitions (These will be exposed to Gemini)
# ---------------------------------------------------------------------------


def get_jira_tasks(
    assignee: str = "me", status: str = "To Do", is_current_sprint: bool = True
) -> str:
    """
    Retrieves tasks from Jira based on assignee and status.

    Args:
        assignee: The person assigned to the task (default: "me").
        status: The current status of the task (e.g., "To Do", "In Progress", "Done").
        is_current_sprint: If True, only returns tasks from the current active sprint.
    """
    logger = get_configured_logger(
        "get_jira_tasks", level="INFO", log_to_file=LOG_FILE, file_mode="a"
    )

    jira_url = os.getenv("JIRA_URL")
    jira_user = os.getenv("JIRA_USER") or os.getenv("JIRA_EMAIL")
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    board_id = os.getenv("JIRA_BOARD_ID")

    if not all([jira_url, jira_user, jira_api_token]):
        return json.dumps(
            {
                "error": "Jira environment variables (URL, USER/EMAIL, TOKEN) are not fully configured."
            }
        )

    auth = HTTPBasicAuth(jira_user, jira_api_token)
    headers = {"Accept": "application/json"}

    sprint_filter = ""
    if is_current_sprint:
        if not board_id:
            print("[Warning] JIRA_BOARD_ID not set; skipping current sprint filter.")
        else:
            try:
                # Note: Agile API endpoints usually don't have /rest/api/3/
                sprint_url = (
                    f"{jira_url.rstrip('/')}/rest/agile/1.0/board/{board_id}/sprint"
                )
                sprint_params = {"state": "active"}
                sprint_resp = requests.get(
                    sprint_url, headers=headers, params=sprint_params, auth=auth
                )
                if sprint_resp.status_code == 200:
                    sprints = sprint_resp.json().get("values", [])
                    if sprints:
                        sprint_id = sprints[0]["id"]
                        sprint_filter = f" AND sprint = {sprint_id}"
                        print(
                            f"[Tool Execution] Found active sprint: {sprints[0].get('name')} (ID: {sprint_id})"
                        )
                    else:
                        print(
                            f"[Warning] No active sprints found for board {board_id}."
                        )
                else:
                    print(
                        f"[Warning] Failed to fetch sprints (HTTP {sprint_resp.status_code}): {sprint_resp.text}"
                    )
            except Exception as e:
                print(f"[Warning] Exception fetching sprints: {e}")

    assignee_query = "currentUser()" if assignee == "me" else f'"{assignee}"'
    jql = f'assignee = {assignee_query} AND status = "{status}"{sprint_filter}'

    print(
        f"[Tool Execution] Fetching Jira tasks for '{assignee}' with status '{status}' using JQL: {jql}..."
    )

    try:
        # Per the 410 error message: migrate to /rest/api/3/search/jql
        url = f"{jira_url.rstrip('/')}/rest/api/3/search/jql"
        params = {"jql": jql, "maxResults": 10, "fields": "*all"}
        response = requests.get(url, headers=headers, params=params, auth=auth)
        response.raise_for_status()

        data = response.json()
        logger.debug(dict(data=data))
        tasks = []
        for issue in data.get("issues", []):
            tasks.append(
                {
                    "id": issue["key"],
                    "title": issue["fields"].get("summary"),
                    "priority": issue["fields"].get("priority", {}).get("name"),
                    "status": issue["fields"].get("status", {}).get("name"),
                    "url": f"{jira_url.rstrip('/')}/browse/{issue['key']}",
                }
            )
        logger.debug(dict(len_tasks=len(tasks)))
        return json.dumps(tasks)
    except Exception as e:
        logger.error(e)
        return json.dumps({"error": f"Failed to fetch Jira tasks: {str(e)}"})


def get_mongo_tasks(
    before: str = None,
    omit_statuses: str = "DONE,FAILED",
) -> str:
    """
    Retrieves personal tasks from the custom MongoDB database.

    Args:
    before: return only tasks with scheduled_date<=before (date should be in YYYY-MM-DD format)
    omit_statuses: omit comma-separated statuses (default is 'DONE,FAILED')
    """
    mongo_uri = os.getenv("MONGO_URI")
    mongo_db_name = os.getenv("MONGO_DB_NAME") or "gstasks"

    if not mongo_uri:
        return json.dumps(
            {"error": "MONGO_URI environment variable is not configured."}
        )

    print(
        f"[Tool Execution] Fetching Mongo tasks (before={before}, omit_statuses={omit_statuses})..."
    )

    logger = get_configured_logger(
        "get_mongo_tasks", level="INFO", log_to_file=LOG_FILE, file_mode="a"
    )
    logger.debug(dict(before=before))

    try:
        client = MongoClient(mongo_uri)
        db = client[mongo_db_name]
        collection = db["tasks"]

        omit_list = [s.strip() for s in omit_statuses.split(",") if s.strip()]

        clauses = []
        # Keep the recent tasks filter if that's intended, but let's make it more robust or remove if not needed.
        clauses.append({"scheduled_date": {"$gt": datetime.datetime(2026, 2, 27)}})

        for s in omit_list:
            clauses.append({"status": {"$ne": s}})

        if before is not None:
            before_dt = datetime.datetime.strptime(before, "%Y-%m-%d")
            clauses.append({"scheduled_date": {"$lte": before_dt}})

        if not clauses:
            query = {}
        elif len(clauses) == 1:
            query = clauses[0]
        else:
            query = {"$and": clauses}

        logger.debug(dict(query=query))

        cursor = collection.find(query).limit(50)
        tasks = []
        for doc in cursor:
            processed_doc = {}
            for k, v in doc.items():
                if k == "_id":
                    processed_doc[k] = str(v)
                elif isinstance(v, datetime.datetime):
                    processed_doc[k] = v.isoformat()
                else:
                    processed_doc[k] = v
            tasks.append(processed_doc)

        client.close()
        logger.debug(f"Found {len(tasks)} tasks")
        return json.dumps(tasks)
    except Exception as e:
        logger.error(f"Error in get_mongo_tasks: {e}", exc_info=True)
        return json.dumps({"error": f"Failed to fetch Mongo tasks: {str(e)}"})


# ---------------------------------------------------------------------------
# Agent Setup & Execution
# ---------------------------------------------------------------------------

logger = get_configured_logger("agent", level="INFO")
request_count = 0


def make_new_session_or_fetch_existing(prefix: str, is_make_new: bool = True) -> str:
    logger = get_configured_logger(
        "make_new_session", level="INFO", log_to_file=LOG_FILE, file_mode="a"
    )

    client = MongoClient(os.environ["FOR_METADATA_MONGO_URI"])
    coll = client["logistics"]["20260321-agent-firestore-sessions"]

    if is_make_new:
        session_id = f"{prefix}_{uuid.uuid4()}"
        coll.insert_one(
            dict(session_id=session_id, prefix=prefix, dt=datetime.datetime.now())
        )
        logger.info(f"[New Session Created] Session ID: {session_id}")
    else:
        r = coll.find_one({"prefix": prefix}, sort=[("dt", DESCENDING)])
        session_id = r["session_id"]
        logger.info(f"fetching most recent session `{session_id}`")
    return session_id


def ask_agent(prompt: str, session_id: str = None) -> str:
    """
    Main function to initialize the Gemini client, bind tools, and generate a response.
    Loads and saves conversation history to/from Firestore for session persistence.

    Args:
        prompt: The user query.
        session_id: A unique ID for the session. If None, a new UUID is generated.

    Returns:
        The session_id used for this interaction.
    """
    logger = get_configured_logger(
        "ask_agent", level="INFO", log_to_file=LOG_FILE, file_mode="a"
    )

    global request_count

    if session_id is None:
        session_id = make_new_session_or_fetch_existing(prefix="task")
    else:
        if not session_id.startswith("task_"):
            session_id = f"task_{session_id}"
        print(f"[Existing Session] Session ID: {session_id}")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return session_id

    api_key = api_key.strip("'\"")
    client = genai.Client(
        api_key=api_key,
    )

    # --- Fetch System Instruction (DB with local fallback) ---
    system_instruction = None
    mongo_uri = os.getenv("MONGO_URI")
    if mongo_uri:
        try:
            m_client = MongoClient(os.environ["FOR_METADATA_MONGO_URI"])
            db_mongo = m_client["logistics"]
            config_doc = db_mongo["20260320-agent-configs"].find_one(
                {"agent_id": "taskmaster"}
            )
            if config_doc and "system_instruction" in config_doc:
                system_instruction = config_doc["system_instruction"]
                print("[Info] Loaded system instruction from MongoDB.")
            m_client.close()
        except Exception as e:
            print(f"[Warning] Failed to fetch system instruction from Mongo: {e}")

    if not system_instruction:
        try:
            with open("system_message_taskmaster.md", "r") as f:
                system_instruction = f.read()
                print("[Info] Loaded system instruction from local file.")
        except FileNotFoundError:
            system_instruction = "You are a helpful task-management assistant."
            print("[Warning] System instruction file not found. Using default.")

    today = datetime.date.today().strftime("%Y-%m-%d")

    # 1. Load existing session history
    contents = load_chat_history(session_id)

    # 2. Add current user prompt
    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=f"Today's date is {today}. User query: {prompt}"
                )
            ],
        )
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[get_jira_tasks, get_mongo_tasks],
        temperature=0.2,
    )

    print(f"User: {prompt}\n")
    print("Agent is thinking...\n---")

    while True:
        request_count += 1
        logger.info(f"Making request #{request_count} to model...")

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=contents,
            config=config,
        )

        # Add the model's response to the conversation history
        contents.append(response.candidates[0].content)

        # Check if there are any tool calls
        tool_calls = [
            part.function_call
            for part in response.candidates[0].content.parts
            if part.function_call
        ]

        if not tool_calls:
            break

        # Process each tool call
        tool_responses = []
        for tool_call in tool_calls:
            function_name = tool_call.name
            args = tool_call.args

            # Dispatch to the correct function
            if function_name == "get_jira_tasks":
                result = get_jira_tasks(**args)
            elif function_name == "get_mongo_tasks":
                result = get_mongo_tasks(**args)
            else:
                result = json.dumps({"error": f"Unknown tool: {function_name}"})

            tool_responses.append(
                types.Part.from_function_response(
                    name=function_name, response={"result": result}
                )
            )

        # Add tool results to the conversation history
        contents.append(types.Content(role="user", parts=tool_responses))

    # 3. Save the updated history back to Firestore
    save_chat_history(session_id, contents)

    print("---\nResponse:")
    print(response.text)
    return session_id, response.text


if __name__ == "__main__":
    import sys

    user_prompt = "What are my most important tasks today?"
    provided_session_id = None

    if len(sys.argv) > 1:
        user_prompt = sys.argv[1]
    if len(sys.argv) > 2:
        provided_session_id = sys.argv[2]

    session_id, response_text = ask_agent(user_prompt, session_id=provided_session_id)

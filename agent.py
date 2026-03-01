import os
import datetime
import json
import requests
from requests.auth import HTTPBasicAuth
from pymongo import MongoClient
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

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
                sprint_url = (
                    f"{jira_url.rstrip('/')}/rest/agile/1.0/board/{board_id}/sprint"
                )
                sprint_params = {"state": "active"}
                sprint_resp = requests.get(
                    sprint_url, headers=headers, params=sprint_params, auth=auth
                )
                sprint_resp.raise_for_status()
                sprints = sprint_resp.json().get("values", [])
                if sprints:
                    sprint_id = sprints[0]["id"]
                    sprint_filter = f" AND sprint = {sprint_id}"
                    print(
                        f"[Tool Execution] Found active sprint: {sprints[0].get('name')} (ID: {sprint_id})"
                    )
                else:
                    print(f"[Warning] No active sprints found for board {board_id}.")
            except Exception as e:
                print(f"[Warning] Failed to fetch sprints: {e}")

    assignee_query = "currentUser()" if assignee == "me" else f'"{assignee}"'
    jql = f'assignee = {assignee_query} AND status = "{status}"{sprint_filter}'

    print(
        f"[Tool Execution] Fetching Jira tasks for '{assignee}' with status '{status}' using JQL: {jql}..."
    )

    try:
        url = f"{jira_url.rstrip('/')}/rest/api/3/search"
        params = {"jql": jql, "maxResults": 10}
        response = requests.get(url, headers=headers, params=params, auth=auth)
        response.raise_for_status()

        data = response.json()
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
        return json.dumps(tasks)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch Jira tasks: {str(e)}"})


def get_mongo_tasks(status: str = "TODO", due_today: bool = True) -> str:
    """
    Retrieves personal tasks from the custom MongoDB database.

    Args:
        status: The status of the task (e.g., "TODO", "DONE", "REGULAR", "FAILED").
        due_today: Boolean indicating if only tasks due or scheduled for today should be returned.
    """
    mongo_uri = os.getenv("MONGO_URI")
    mongo_db_name = os.getenv("MONGO_DB_NAME") or "gstasks"

    if not mongo_uri:
        return json.dumps(
            {"error": "MONGO_URI environment variable is not configured."}
        )

    print(
        f"[Tool Execution] Fetching Mongo tasks (Status: {status}, Due Today: {due_today})..."
    )

    try:
        client = MongoClient(mongo_uri)
        db = client[mongo_db_name]
        collection = db["tasks"]

        query = {}
        if status:
            query["status"] = status

        if due_today:
            today = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_str = today.strftime("%Y-%m-%d")
            date_query = {"$in": [today, today_str]}
            query["$or"] = [{"scheduled_date": date_query}, {"due": date_query}]

        cursor = collection.find(query).limit(20)
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
        return json.dumps(tasks)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch Mongo tasks: {str(e)}"})


# ---------------------------------------------------------------------------
# Agent Setup & Execution
# ---------------------------------------------------------------------------


def ask_agent(prompt: str) -> None:
    """
    Main function to initialize the Gemini client, bind tools, and generate a response.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return

    api_key = api_key.strip("'\"")
    client = genai.Client(api_key=api_key)

    try:
        with open("GEMINI.md", "r") as f:
            system_instruction = f.read()
    except FileNotFoundError:
        system_instruction = "You are a helpful task-management assistant."

    today = datetime.date.today().strftime("%Y-%m-%d")
    full_prompt = f"Today's date is {today}. User query: {prompt}"

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[get_jira_tasks, get_mongo_tasks],
        temperature=0.2,
    )

    print(f"User: {prompt}\n")
    print("Agent is thinking...\n---")

    # Using gemini-flash-latest as it is confirmed to be available.
    response = client.models.generate_content(
        # model="gemini-flash-latest",
        model="gemini-2.5-flash-lite",
        contents=full_prompt,
        config=config,
    )

    print("---\nResponse:")
    print(response.text)


if __name__ == "__main__":
    ask_agent("What tasks should I do today?")

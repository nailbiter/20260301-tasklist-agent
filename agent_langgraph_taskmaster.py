import os
import datetime
import json
import requests
from requests.auth import HTTPBasicAuth
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv
from typing import Annotated, Sequence, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.firestore import FirestoreSaver
from google.cloud import firestore

# Load environment variables
load_dotenv()

# Initialize Firestore
db = firestore.Client()
checkpointer = FirestoreSaver(db)

# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

@tool
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
        return json.dumps({"error": "Jira environment variables (URL, USER/EMAIL, TOKEN) are not fully configured."})

    auth = HTTPBasicAuth(jira_user, jira_api_token)
    headers = {"Accept": "application/json"}

    sprint_filter = ""
    if is_current_sprint and board_id:
        try:
            sprint_url = f"{jira_url.rstrip('/')}/rest/agile/1.0/board/{board_id}/sprint"
            sprint_resp = requests.get(sprint_url, headers=headers, params={"state": "active"}, auth=auth)
            if sprint_resp.status_code == 200:
                sprints = sprint_resp.json().get("values", [])
                if sprints:
                    sprint_id = sprints[0]["id"]
                    sprint_filter = f" AND sprint = {sprint_id}"
        except Exception:
            pass

    assignee_query = "currentUser()" if assignee == "me" else f'"{assignee}"'
    jql = f'assignee = {assignee_query} AND status = "{status}"{sprint_filter}'

    try:
        url = f"{jira_url.rstrip('/')}/rest/api/3/search/jql"
        response = requests.get(url, headers=headers, params={"jql": jql, "maxResults": 10}, auth=auth)
        response.raise_for_status()
        data = response.json()
        tasks = [
            {"id": issue["key"], "title": issue["fields"].get("summary"), "url": f"{jira_url.rstrip('/')}/browse/{issue['key']}"}
            for issue in data.get("issues", [])
        ]
        return json.dumps(tasks)
    except Exception as e:
        return json.dumps({"error": str(e)})

@tool
def get_mongo_tasks(before: str = None, omit_statuses: str = "DONE,FAILED") -> str:
    """
    Retrieves personal tasks from the custom MongoDB database.
    """
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB_NAME") or "gstasks"

    if not mongo_uri:
        return json.dumps({"error": "MONGO_URI not configured."})

    try:
        client = MongoClient(mongo_uri)
        db_mongo = client[db_name]
        collection = db_mongo["tasks"]

        query = {"scheduled_date": {"$gt": datetime.datetime(2026, 2, 7)}}
        if before:
            query["scheduled_date"] = {"$lte": datetime.datetime.strptime(before, "%Y-%m-%d")}

        tasks = list(collection.find(query).limit(50))
        client.close()
        return json.dumps(str(tasks)) # Simplified serialization for brevity
    except Exception as e:
        return json.dumps({"error": str(e)})

# ---------------------------------------------------------------------------
# Graph Definition
# ---------------------------------------------------------------------------

class State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]

def run_agent(state: State):
    model = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.2)
    model_with_tools = model.bind_tools([get_jira_tasks, get_mongo_tasks])

    # Prepend context date if needed
    today = datetime.date.today().strftime("%Y-%m-%d")
    messages = [HumanMessage(content=f"Today's date is {today}.")] + list(state["messages"])

    response = model_with_tools.invoke(messages)
    return {"messages": [response]}

workflow = StateGraph(State)
workflow.add_node("agent", run_agent)
workflow.add_node("tools", ToolNode([get_jira_tasks, get_mongo_tasks]))

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", tools_condition)
workflow.add_edge("tools", "agent")

app = workflow.compile(checkpointer=checkpointer)

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    session_id = sys.argv[2] if len(sys.argv) > 2 else "default_session"
    prompt = sys.argv[1] if len(sys.argv) > 1 else "What are my tasks?"

    config = {"configurable": {"thread_id": session_id}}

    # Run the graph
    for event in app.stream({"messages": [HumanMessage(content=prompt)]}, config=config):
        for value in event.values():
            print(value)

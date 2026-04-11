import os
import datetime
import json
from pymongo import MongoClient
from dotenv import load_dotenv
from typing import Annotated, Sequence, TypedDict
from jinja2 import Template
import pandas as pd

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

from alex_leontiev_toolbox_python.utils.logging_helpers import get_configured_logger

# Load environment variables
load_dotenv()

# logging
_log_file = os.path.join(
    ".logs",
    f"agent_langgraph_taskmaster-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.log.txt",
)
global_logger = get_configured_logger(
    "agent_langgraph_taskmaster", log_to_file=_log_file, level="WARNING"
)

# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------


@tool
def mark_task_done(uuid: str):
    """
    Mark a task as DONE by its UUID.
    """
    client = MongoClient(os.getenv("MONGO_URI"))
    db_mongo = client[os.getenv("MONGO_DB_NAME") or "gstasks"]
    collection = db_mongo["tasks"]
    result = collection.update_one({"uuid": uuid}, {"$set": {"status": "DONE"}})
    client.close()
    return f"Task {uuid} marked as DONE"


@tool
def postpone_task(uuid: str, new_date: str):
    """
    Postpone a task to a new date (YYYY-MM-DD).
    """
    client = MongoClient(os.getenv("MONGO_URI"))
    db_mongo = client[os.getenv("MONGO_DB_NAME") or "gstasks"]
    collection = db_mongo["tasks"]
    new_dt = pd.to_datetime(new_date)
    result = collection.update_one({"uuid": uuid}, {"$set": {"scheduled_date": new_dt}})
    client.close()
    return f"Task {uuid} postponed to {new_date}"


@tool
def get_mongo_tasks(
    scheduled_before: str = None,
    scheduled_on: str = None,
    scheduled_after: str = None,
    name_regex: str = None,
    omit_statuses: str = "DONE,FAILED",
    search_all: bool = False,
) -> str:
    """
    Retrieves personal tasks from the custom MongoDB database.
    By default, it only returns tasks scheduled after 2026-02-07 unless search_all is True.

    Args:
        scheduled_before: Return tasks scheduled on or before this date. Format: YYYY-MM-DD.
        scheduled_on: Return tasks scheduled exactly on this date. Format: YYYY-MM-DD.
        scheduled_after: Return tasks scheduled on or after this date (e.g., for finding future tasks). Format: YYYY-MM-DD.
        name_regex: Use a case-insensitive regular expression to search for specific words or patterns in the task name.
        omit_statuses: Comma-separated statuses to exclude. Default is "DONE,FAILED".
        search_all: Set to True to completely bypass default date restrictions when searching across all time (e.g., global searches).
    """
    mongo_uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB_NAME") or "gstasks"
    logger = global_logger.getChild("get_mongo_tasks")

    if not mongo_uri:
        return json.dumps({"error": "MONGO_URI not configured."})

    try:
        client = MongoClient(mongo_uri)
        db_mongo = client[db_name]
        collection = db_mongo["tasks"]

        queries = []
        # this should not be overridable
        queries.append({"scheduled_date": {"$gt": datetime.datetime(2026, 2, 7)}})

        if not search_all:
            logger.debug(dict(search_all=search_all))

        if scheduled_before:
            query = {}
            query["scheduled_date"] = {"$lte": pd.to_datetime(scheduled_before)}
            queries.append(query)
        if scheduled_on:
            query = {}
            dt = pd.to_datetime(scheduled_on)
            start_of_day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            query["scheduled_date"] = {"$gte": start_of_day, "$lte": end_of_day}
            queries.append(query)
        if scheduled_after:
            query = {}
            query["scheduled_date"] = {"$gte": pd.to_datetime(scheduled_after)}
            queries.append(query)

        if name_regex:
            queries.append({"name": {"$regex": name_regex, "$options": "i"}})
        for status in omit_statuses.split(","):
            queries.append({"status": {"$ne": status}})

        query = {"$and": queries} if queries else {}
        logger.debug(dict(query=query))

        # Project only allowed fields
        projection = {
            "_id": 0,
            "name": 1,
            "scheduled_date": 1,
            "status": 1,
            "due": 1,
            "tags": 1,
            "comment": 1,
            "url": 1,
            "uuid": 1,
        }

        tasks = list(collection.find(query, projection).limit(50))

        # Resolve tags
        tag_uuids = set()
        for t in tasks:
            if "tags" in t and isinstance(t["tags"], list):
                for tag_id in t["tags"]:
                    tag_uuids.add(tag_id)

        if tag_uuids:
            tags_collection = db_mongo["tags"]
            tags_cursor = tags_collection.find({"uuid": {"$in": list(tag_uuids)}})
            tag_map = {doc["uuid"]: doc.get("name", doc["uuid"]) for doc in tags_cursor}

            for t in tasks:
                tag_names = []
                if "tags" in t and isinstance(t["tags"], list):
                    for tag_id in t["tags"]:
                        if tag_id in tag_map:
                            tag_names.append(tag_map[tag_id])
                t["tags"] = ", ".join(tag_names) if tag_names else ""
        else:
            for t in tasks:
                t["tags"] = ""

        # Convert datetimes and clean up JSON-invalid values
        for t in tasks:
            # Impute status
            if not t.get("status"):
                t["status"] = "TODO"

            for k, v in t.items():
                if isinstance(v, datetime.datetime):
                    t[k] = v.strftime("%Y-%m-%d")
                elif isinstance(v, float) and (v != v):  # check for NaN
                    t[k] = None
        client.close()
        logger.debug(dict(tasks=tasks))

        return json.dumps(tasks)
    except Exception as e:
        logger.error(e)
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Graph Definition
# ---------------------------------------------------------------------------


class State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


def get_system_message():
    today = datetime.date.today().strftime("%Y-%m-%d")
    with open("system_message_taskmaster.jinja.md", "r") as f:
        template = Template(f.read())
    return SystemMessage(content=template.render(date=today))


tools = [get_mongo_tasks, mark_task_done, postpone_task]


def run_agent(state: State):
    model = ChatGoogleGenerativeAI(temperature=0.2, model="gemini-2.5-flash-lite")
    model_with_tools = model.bind_tools(tools)

    system_msg = get_system_message()

    # Prepend system message if not present
    messages = list(state["messages"])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [system_msg] + messages

    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


# --- New Action Node ---


def action_node(state: State):
    last_message = state["messages"][-1]
    tool_messages = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        args = tool_call["args"]

        res = None
        if tool_name == "get_mongo_tasks":
            res = get_mongo_tasks.invoke(args)
        elif tool_name == "mark_task_done":
            res = mark_task_done.invoke(args)
        elif tool_name == "postpone_task":
            res = postpone_task.invoke(args)

        tool_messages.append(
            ToolMessage(content=str(res), tool_call_id=tool_call["id"])
        )
    return {"messages": tool_messages}


def should_continue(state: State) -> str:
    messages = state["messages"]
    last_message = messages[-1]
    if not last_message.tool_calls:
        return END

    # Interrupt only if edit tools are called
    edit_tools = ["mark_task_done", "postpone_task"]
    if any(tc["name"] in edit_tools for tc in last_message.tool_calls):
        return "action"
    return "read_action"


workflow = StateGraph(State)
workflow.add_node("agent", run_agent)
workflow.add_node("action", action_node)
workflow.add_node("read_action", action_node)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {"action": "action", "read_action": "read_action", END: END},
)
workflow.add_edge("action", "agent")
workflow.add_edge("read_action", "agent")

compile_kwargs = {"interrupt_before": ["action"]}
if not os.getenv("IS_LANGGRAPH_DEV", "1") == "1":
    checkpointer = MemorySaver()
    compile_kwargs["checkpointer"] = checkpointer

app = workflow.compile(**compile_kwargs)

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    session_id = sys.argv[2] if len(sys.argv) > 2 else "default_session"
    prompt = sys.argv[1] if len(sys.argv) > 1 else "What are my tasks?"

    config = {"configurable": {"thread_id": session_id}}

    # Run the graph
    for event in app.stream(
        {"messages": [HumanMessage(content=prompt)]}, config=config
    ):
        for value in event.values():
            print(value)

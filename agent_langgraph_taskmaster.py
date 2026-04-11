import os
import datetime
import json
from pymongo import MongoClient
from dotenv import load_dotenv
from typing import Annotated, Sequence, TypedDict
from jinja2 import Template
import pandas as pd

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START
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
def get_mongo_tasks(
    before: str = None, on_date: str = None, omit_statuses: str = "DONE,FAILED"
) -> str:
    """
    Retrieves personal tasks from the custom MongoDB database.

    Args:
        before: Return only tasks with scheduled_date <= before. Format: YYYY-MM-DD.
        on_date: Return only tasks with scheduled_date == on_date. Format: YYYY-MM-DD.
        omit_statuses: Comma-separated statuses to omit (default: "DONE,FAILED").
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

        queries = [
            ## SIC! do not remove this, this is important
            {"scheduled_date": {"$gt": datetime.datetime(2026, 2, 7)}},
        ]

        if before:
            query = {}
            query["scheduled_date"] = {"$lte": pd.to_datetime(before)}
            queries.append(query)
        if on_date:
            query = {}
            dt = pd.to_datetime(on_date)
            start_of_day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            query["scheduled_date"] = {"$gte": start_of_day, "$lte": end_of_day}
            queries.append(query)
        for status in omit_statuses.split(","):
            queries.append({"status": {"$ne": status}})

        query = {"$and": queries}
        logger.debug(dict(query=query))

        # Project only allowed fields
        projection = {
            "_id": 0,
            "name": 1,
            "scheduled_date": 1,
            "status": 1,
            "when": 0,
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


def run_agent(state: State):
    model = ChatGoogleGenerativeAI(temperature=0.2, model="gemini-2.5-flash-lite")
    model_with_tools = model.bind_tools([get_mongo_tasks])

    system_msg = get_system_message()

    # Prepend system message if not present
    messages = list(state["messages"])
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [system_msg] + messages

    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


workflow = StateGraph(State)
workflow.add_node("agent", run_agent)
workflow.add_node("tools", ToolNode([get_mongo_tasks]))

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", tools_condition)
workflow.add_edge("tools", "agent")

compile_kwargs = {}
if not os.getenv("IS_LANGGRAPH_DEV", "1") == "1":
    # For persistent running (e.g. cloud), you'd swap this back to Firestore
    # For now, we default to MemorySaver as requested
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

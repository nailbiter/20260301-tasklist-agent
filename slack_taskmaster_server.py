import hashlib
import hmac
import logging
import os
import threading
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.firestore import FirestoreSaver

from agent_langgraph_taskmaster import workflow

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
TARGET_CHANNEL_ID = os.environ.get("TARGET_CHANNEL_ID", "")

# Compile graph for web use: Firestore checkpointer, no interrupt_before
checkpointer = FirestoreSaver()
langgraph_app = workflow.compile(checkpointer=checkpointer)


def _verify_signature(req) -> bool:
    ts = req.headers.get("X-Slack-Request-Timestamp", "")
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except (ValueError, TypeError):
        return False
    base = f"v0:{ts}:{req.get_data(as_text=True)}"
    expected = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(), base.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, req.headers.get("X-Slack-Signature", ""))


def _run_agent(thread_id: str, text: str):
    config = {"configurable": {"thread_id": thread_id}}
    try:
        for _ in langgraph_app.stream(
            {"messages": [HumanMessage(content=text)]}, config=config
        ):
            pass
    except Exception as e:
        logger.error(f"Agent error for thread {thread_id}: {e}", exc_info=True)


@app.post("/")
def slack_events():
    if not _verify_signature(request):
        return jsonify({"error": "invalid signature"}), 403

    data = request.json or {}

    # Slack URL-verification handshake
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    event = data.get("event", {})

    # Ignore non-messages, bots, subtypes (edits/deletions), wrong channel
    if event.get("type") != "message":
        return jsonify({"ok": True})
    if event.get("bot_id") or event.get("subtype"):
        return jsonify({"ok": True})
    if TARGET_CHANNEL_ID and event.get("channel") != TARGET_CHANNEL_ID:
        return jsonify({"ok": True})

    text = event.get("text", "")
    user_id = event.get("user", "unknown")
    logger.info(f"Dispatching agent for user={user_id} text={text!r}")

    # Respond to Slack within 3 s; run agent in background thread
    t = threading.Thread(target=_run_agent, args=(user_id, text), daemon=True)
    t.start()

    return jsonify({"ok": True})

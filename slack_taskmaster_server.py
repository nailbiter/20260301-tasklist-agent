import datetime
import hashlib
import hmac
import logging
import os
import threading
import time
import uuid
from typing import Callable

import requests as http_requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from langchain_core.messages import HumanMessage
from langgraph_checkpoint_firestore import FirestoreSaver
from pymongo import MongoClient
from slack_sdk import WebClient

from agent_langgraph_taskmaster import workflow

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
TARGET_CHANNEL_ID = os.environ.get("TARGET_CHANNEL_ID", "")

slack_client = WebClient(token=SLACK_BOT_TOKEN)

# Compile graph for web use: Firestore checkpointer, no interrupt_before
checkpointer = FirestoreSaver()
langgraph_app = workflow.compile(checkpointer=checkpointer)

# MongoDB-backed session store
_meta_client = MongoClient(os.environ["FOR_METADATA_MONGO_URI"])
_sessions_col = _meta_client["logistics"]["20260321-agent-firestore-sessions"]


def _get_or_create_session(user_id: str) -> str:
    doc = _sessions_col.find_one({"user_id": user_id})
    if doc:
        return doc["session_id"]
    session_id = f"taskmaster_langgraph_{uuid.uuid4()}"
    _sessions_col.insert_one({
        "user_id": user_id,
        "session_id": session_id,
        "prefix": "taskmaster_langgraph",
        "dt": datetime.datetime.utcnow(),
    })
    return session_id


def _reset_session(user_id: str) -> str:
    session_id = f"taskmaster_langgraph_{uuid.uuid4()}"
    _sessions_col.update_one(
        {"user_id": user_id},
        {"$set": {"session_id": session_id, "dt": datetime.datetime.utcnow()}},
        upsert=True,
    )
    logger.info(f"Session reset for user={user_id}, new session_id={session_id}")
    return session_id


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


def _run_agent(thread_id: str, text: str, reply_fn: Callable[[str], None]):
    config = {"configurable": {"thread_id": thread_id}}
    try:
        for _ in langgraph_app.stream(
            {"messages": [HumanMessage(content=text)]}, config=config
        ):
            pass
        final_state = langgraph_app.get_state(config)
        messages = final_state.values.get("messages", [])
        last_ai = next((m for m in reversed(messages) if m.type == "ai"), None)
        if last_ai and last_ai.content:
            reply_fn(last_ai.content)
    except Exception as e:
        logger.error(f"Agent error for thread {thread_id}: {e}", exc_info=True)


def _channel_reply(channel: str, thread_ts: str = None) -> Callable[[str], None]:
    def reply(text: str):
        slack_client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    return reply


def _response_url_reply(response_url: str, ephemeral: bool = True) -> Callable[[str], None]:
    def reply(text: str):
        http_requests.post(response_url, json={
            "text": text,
            "response_type": "ephemeral" if ephemeral else "in_channel",
        })
    return reply


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

    text = event.get("text", "").strip()
    user_id = event.get("user", "unknown")
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts")

    if text.lower() in ("reset", "/reset", "reset session"):
        _reset_session(user_id)
        slack_client.chat_postMessage(channel=channel, text="Session reset. Starting fresh!", thread_ts=thread_ts)
        return jsonify({"ok": True})

    thread_id = _get_or_create_session(user_id)
    logger.info(f"Dispatching agent for user={user_id} thread={thread_id} text={text!r}")

    reply_fn = _channel_reply(channel, thread_ts)
    t = threading.Thread(target=_run_agent, args=(thread_id, text, reply_fn), daemon=True)
    t.start()

    return jsonify({"ok": True})


def _dispatch(user_id: str, text: str, reply_fn: Callable[[str], None], reset_reply: Callable[[str], None]):
    """Shared dispatch logic for both routes."""
    text = text.strip()
    if text.lower() in ("reset", "/reset", "reset session"):
        _reset_session(user_id)
        reset_reply("Session reset. Starting fresh!")
        return
    thread_id = _get_or_create_session(user_id)
    logger.info(f"Dispatching agent for user={user_id} thread={thread_id} text={text!r}")
    threading.Thread(target=_run_agent, args=(thread_id, text, reply_fn), daemon=True).start()


@app.post("/slack/ingress")
def slack_ingress():
    # Ignore Slack retries (Events API only; slash commands don't retry)
    if request.headers.get("X-Slack-Retry-Num"):
        return "OK", 200

    if not _verify_signature(request):
        return jsonify({"error": "invalid signature"}), 403

    if request.is_json:
        data = request.json or {}

        if data.get("type") == "url_verification":
            return jsonify({"challenge": data["challenge"]})

        event = data.get("event", {})
        if event.get("type") != "message" or event.get("bot_id") or event.get("subtype"):
            return jsonify({"ok": True})
        if TARGET_CHANNEL_ID and event.get("channel") != TARGET_CHANNEL_ID:
            return jsonify({"ok": True})

        user_id = event.get("user", "unknown")
        text = event.get("text", "")
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        reply_fn = _channel_reply(channel, thread_ts)
        _dispatch(user_id, text, reply_fn, reply_fn)
    else:
        # Slash command (application/x-www-form-urlencoded)
        data = request.form
        user_id = data.get("user_id", "unknown")
        text = data.get("text", "")
        response_url = data.get("response_url", "")
        reply_fn = _response_url_reply(response_url, ephemeral=True)
        _dispatch(user_id, text, reply_fn, reply_fn)

    return jsonify({"ok": True})

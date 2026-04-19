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
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph_checkpoint_firestore import FirestoreSaver
from pymongo import MongoClient
from slack_sdk import WebClient

from agent_langgraph_taskmaster import workflow

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

app = Flask(__name__)

SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
TARGET_CHANNEL_ID = os.environ.get("TARGET_CHANNEL_ID", "")

slack_client = WebClient(token=SLACK_BOT_TOKEN)

_langgraph_app = None
_sessions_col = None
_init_lock = threading.Lock()


def _get_app():
    global _langgraph_app
    if _langgraph_app is None:
        with _init_lock:
            if _langgraph_app is None:
                checkpointer = FirestoreSaver(
                    project_id=os.environ["GOOGLE_CLOUD_PROJECT"]
                )
                _langgraph_app = workflow.compile(
                    checkpointer=checkpointer, interrupt_before=["action"]
                )
    return _langgraph_app


def _get_sessions_col():
    global _sessions_col
    if _sessions_col is None:
        with _init_lock:
            if _sessions_col is None:
                meta_client = MongoClient(os.environ["FOR_METADATA_MONGO_URI"])
                _sessions_col = meta_client["logistics"][
                    "20260321-agent-firestore-sessions"
                ]
    return _sessions_col


def _get_or_create_session(user_id: str) -> str:
    doc = _get_sessions_col().find_one({"user_id": user_id})
    if doc:
        return doc["session_id"]
    session_id = f"taskmaster_langgraph_{uuid.uuid4()}"
    _get_sessions_col().insert_one(
        {
            "user_id": user_id,
            "session_id": session_id,
            "prefix": "taskmaster_langgraph",
            "dt": datetime.datetime.utcnow(),
        }
    )
    return session_id


def _reset_session(user_id: str) -> str:
    session_id = f"taskmaster_langgraph_{uuid.uuid4()}"
    _get_sessions_col().update_one(
        {"user_id": user_id},
        {
            "$set": {
                "session_id": session_id,
                "dt": datetime.datetime.utcnow(),
                "pending_action": None,
            }
        },
        upsert=True,
    )
    logger.info(f"Session reset for user={user_id}, new session_id={session_id}")
    return session_id


def _set_pending(user_id: str, calls_desc: str):
    _get_sessions_col().update_one(
        {"user_id": user_id},
        {"$set": {"pending_action": calls_desc}},
    )


def _clear_pending(user_id: str):
    _get_sessions_col().update_one(
        {"user_id": user_id},
        {"$unset": {"pending_action": ""}},
    )


def _get_pending(user_id: str) -> str | None:
    doc = _get_sessions_col().find_one({"user_id": user_id}, {"pending_action": 1})
    return doc.get("pending_action") if doc else None


def _verify_signature(req) -> bool:
    ts = req.headers.get("X-Slack-Request-Timestamp", "")
    signature = req.headers.get("X-Slack-Signature", "")
    try:
        if abs(time.time() - int(ts)) > 300:
            logger.error(
                f"Signature verification failed: timestamp too old (ts={ts}, now={time.time()})"
            )
            return False
    except (ValueError, TypeError):
        logger.error(f"Signature verification failed: invalid timestamp (ts={ts})")
        return False

    body = req.get_data(as_text=True)
    base = f"v0:{ts}:{body}"
    expected = (
        "v0="
        + hmac.new(
            SLACK_SIGNING_SECRET.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
    )

    result = hmac.compare_digest(expected, signature)
    if not result:
        logger.error(f"Signature verification failed!")
        logger.error(f"  Timestamp: {ts}")
        logger.error(f"  Signature: {signature}")
        logger.error(f"  Expected:  {expected}")
        # logger.debug(f"  Base string: {base}") # Careful with secrets if logging base
    return result


def _post_final_reply(thread_id: str, reply_fn: Callable[[str], None]):
    """Read the last AI message from graph state and send it."""
    final_state = _get_app().get_state({"configurable": {"thread_id": thread_id}})
    messages = final_state.values.get("messages", [])
    last_ai = next((m for m in reversed(messages) if m.type == "ai"), None)
    if last_ai and last_ai.content:
        reply_fn(last_ai.content)


def _run_agent(
    user_id: str, thread_id: str, text: str, reply_fn: Callable[[str], None]
):
    config = {"configurable": {"thread_id": thread_id}}
    try:
        for _ in _get_app().stream(
            {"messages": [HumanMessage(content=text)]}, config=config
        ):
            pass

        snapshot = _get_app().get_state(config)
        if snapshot.next:
            # Interrupted before an edit tool — ask for confirmation
            messages = snapshot.values.get("messages", [])
            last_ai = next(
                (
                    m
                    for m in reversed(messages)
                    if hasattr(m, "tool_calls") and m.tool_calls
                ),
                None,
            )
            if last_ai:
                calls_desc = ", ".join(
                    f"{tc['name']}({tc['args']})" for tc in last_ai.tool_calls
                )
                _set_pending(user_id, calls_desc)
                reply_fn(
                    f"About to call: {calls_desc}\nReply *confirm* to proceed or *reject* to cancel."
                )
        else:
            _clear_pending(user_id)
            _post_final_reply(thread_id, reply_fn)
    except Exception as e:
        logger.error(f"Agent error for thread {thread_id}: {e}", exc_info=True)


def _confirm_action(user_id: str, thread_id: str, reply_fn: Callable[[str], None]):
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = _get_app().get_state(config)
        if not snapshot.next:
            reply_fn("No pending action to confirm.")
            return
        for _ in _get_app().stream(None, config):
            pass
        _clear_pending(user_id)
        _post_final_reply(thread_id, reply_fn)
    except Exception as e:
        logger.error(f"Confirm error for thread {thread_id}: {e}", exc_info=True)


def _reject_action(user_id: str, thread_id: str, reply_fn: Callable[[str], None]):
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = _get_app().get_state(config)
        if not snapshot.next:
            reply_fn("No pending action to reject.")
            return
        messages = snapshot.values.get("messages", [])
        last_ai = next(
            (
                m
                for m in reversed(messages)
                if hasattr(m, "tool_calls") and m.tool_calls
            ),
            None,
        )
        if last_ai:
            cancel_msgs = [
                ToolMessage(content="Action cancelled by user.", tool_call_id=tc["id"])
                for tc in last_ai.tool_calls
            ]
            _get_app().update_state(config, {"messages": cancel_msgs}, as_node="action")
            for _ in _get_app().stream(None, config):
                pass
        _clear_pending(user_id)
        _post_final_reply(thread_id, reply_fn)
    except Exception as e:
        logger.error(f"Reject error for thread {thread_id}: {e}", exc_info=True)


def _channel_reply(channel: str, thread_ts: str = None) -> Callable[[str], None]:
    def reply(text: str):
        slack_client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)

    return reply


def _response_url_reply(
    response_url: str, ephemeral: bool = True
) -> Callable[[str], None]:
    def reply(text: str):
        http_requests.post(
            response_url,
            json={
                "text": text,
                "response_type": "ephemeral" if ephemeral else "in_channel",
            },
        )

    return reply


def _dispatch(
    user_id: str,
    text: str,
    reply_fn: Callable[[str], None],
    reset_reply: Callable[[str], None],
):
    """Shared dispatch logic for both routes."""
    text = text.strip()
    if not text:
        return
    cmd = text.lower()

    logger.debug(dict(who="_dispatch", user_id=user_id, text=text, cmd=cmd))

    if cmd in ("reset", "/reset", "reset session", "reset-session", "/reset-session"):
        _reset_session(user_id)
        reset_reply("Session reset. Starting fresh!")
        return

    thread_id = _get_or_create_session(user_id)

    if cmd == "confirm":
        if not _get_pending(user_id):
            reply_fn("No pending action to confirm.")
            return
        threading.Thread(
            target=_confirm_action, args=(user_id, thread_id, reply_fn), daemon=True
        ).start()
        return

    if cmd == "reject":
        if not _get_pending(user_id):
            reply_fn("No pending action to reject.")
            return
        threading.Thread(
            target=_reject_action, args=(user_id, thread_id, reply_fn), daemon=True
        ).start()
        return

    logger.info(
        f"Dispatching agent for user={user_id} thread={thread_id} text={text!r}"
    )
    threading.Thread(
        target=_run_agent, args=(user_id, thread_id, text, reply_fn), daemon=True
    ).start()


@app.post("/")
def slack_events():
    data = request.get_json(silent=True) or {}

    # Handle Slack URL verification challenge without signature verification
    # if it is a challenge request.
    if data.get("type") == "url_verification":
        logger.info("Handling Slack URL verification challenge")
        return jsonify({"challenge": data["challenge"]})

    if not _verify_signature(request):
        return jsonify({"error": "invalid signature"}), 403

    event = data.get("event", {})

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
    reply_fn = _channel_reply(channel, thread_ts)
    threading.Thread(
        target=_dispatch, args=(user_id, text, reply_fn, reply_fn), daemon=True
    ).start()
    return jsonify({"ok": True})


@app.post("/slack/ingress")
def slack_ingress():
    logger.debug(
        dict(headers=request.headers, is_json=request.is_json, request=request)
    )
    if request.headers.get("X-Slack-Retry-Num"):
        return "OK", 200

    # For JSON requests, we can check for url_verification before signature
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if data.get("type") == "url_verification":
            logger.info("Handling Slack URL verification challenge (ingress)")
            return jsonify({"challenge": data["challenge"]})

    if not _verify_signature(request):
        return jsonify({"error": "invalid signature"}), 403

    if request.is_json:
        data = request.json or {}

        event = data.get("event", {})
        if (
            event.get("type") != "message"
            or event.get("bot_id")
            or event.get("subtype")
        ):
            return jsonify({"ok": True})
        if TARGET_CHANNEL_ID and event.get("channel") != TARGET_CHANNEL_ID:
            return jsonify({"ok": True})

        user_id = event.get("user", "unknown")
        text = event.get("text", "")
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        reply_fn = _channel_reply(channel, thread_ts)
        threading.Thread(
            target=_dispatch, args=(user_id, text, reply_fn, reply_fn), daemon=True
        ).start()
    else:
        data = request.form
        user_id = data.get("user_id", "unknown")
        text = data.get("text", "").strip() or data.get("command", "").strip()
        response_url = data.get("response_url", "")
        reply_fn = _response_url_reply(response_url, ephemeral=True)
        threading.Thread(
            target=_dispatch, args=(user_id, text, reply_fn, reply_fn), daemon=True
        ).start()
        return jsonify({"text": "Got it, working on it..."}), 200

    return jsonify({"ok": True})

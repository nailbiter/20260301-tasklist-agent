import os
import hmac
import hashlib
import time
import sys
import threading
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv

# Importing your specific agent logic
import agent_taskmaster

# Using your utility logger
from utils import get_configured_logger

# Load .env for local development
load_dotenv()

app = Flask(__name__)
logger = get_configured_logger("slack_gateway")


def get_env_or_fail(var_name):
    value = os.environ.get(var_name)
    if not value:
        logger.error(f"Required environment variable '{var_name}' is not set.")
        sys.exit(1)
    return value


# Configuration
SLACK_SIGNING_SECRET = get_env_or_fail("SLACK_SIGNING_SECRET")
SLACK_BOT_TOKEN = get_env_or_fail("SLACK_BOT_TOKEN")
TARGET_CHANNEL_ID = get_env_or_fail("TARGET_CHANNEL_ID")


def verify_slack_signature(headers, body):
    timestamp = headers.get("X-Slack-Request-Timestamp")
    signature = headers.get("X-Slack-Signature")

    if not timestamp or not signature:
        return False
    # Standard 5-minute window for security
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    my_sig = (
        "v0="
        + hmac.new(
            bytes(SLACK_SIGNING_SECRET, "utf-8"),
            bytes(sig_basestring, "utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(my_sig, signature)


def process_event(event):
    """
    Background worker to handle Gemini logic and respond to Slack.
    Decoupled from the HTTP response to beat the 3-second timeout.
    """
    user_text = event.get("text", "").strip()
    channel = event.get("channel")
    user_id = event.get("user")

    logger.info(f"Background processing started for user {user_id}: {user_text}")

    # Session Management logic
    is_reset = user_text.lower() == "reset session"
    
    try:
        # Step 1: Manage Session
        session_id = agent_taskmaster.make_new_session_or_fetch_existing(
            prefix="task", is_make_new=is_reset
        )

        if is_reset:
            response_text = f"Session has been reset. (New Session ID: {session_id})"
        else:
            # Step 2: Call the Gemini Agent
            # This is the 'heavy' part that usually triggers the Slack retry
            _, response_text = agent_taskmaster.ask_agent(
                user_text, session_id=session_id
            )
            
    except Exception as e:
        logger.error(f"Error processing agent query: {e}", exc_info=True)
        response_text = f"⚠️ Error processing your request: {str(e)}"

    # Step 3: Post back to Slack
    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={
                "channel": channel, 
                "text": response_text
            },
            timeout=10,
        )
        logger.info(f"Successfully posted response to Slack for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to post message back to Slack: {e}")


@app.route("/slack/ingress", methods=["POST"])
def slack_ingress():
    # --- FIX 1: RETRY FILTERING ---
    # Slack retries if it doesn't get a 200 OK within 3 seconds.
    # We check the header and kill the retry immediately to prevent duplicate posts.
    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.info(f"Ignoring Slack retry attempt #{retry_num}")
        return "OK", 200

    raw_data = request.get_data()
    data = request.json

    # 1. URL Verification (Standard Slack Handshake)
    if data and data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # 2. Signature Verification (Security)
    if not verify_slack_signature(request.headers, raw_data):
        logger.warning("Unauthorized request signature rejected.")
        return "Unauthorized", 403

    # 3. Event Extraction
    event = data.get("event", {})

    # Filter for valid messages in your target channel
    if (
        event.get("type") == "message"
        and event.get("channel") == TARGET_CHANNEL_ID
        and "bot_id" not in event
        and event.get("subtype") is None
    ):
        # --- FIX 2: ASYNCHRONOUS PROCESSING ---
        # Spin up a thread and immediately return 200 OK to Slack.
        worker = threading.Thread(target=process_event, args=(event,))
        worker.start()

        # Returning here stops Slack from counting to 3 and retrying.
        return "OK", 200

    # Default fall-through for events we don't care about (e.g., joins, other channels)
    return "OK", 200


if __name__ == "__main__":
    # Cloud Run uses the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
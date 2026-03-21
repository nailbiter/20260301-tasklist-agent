import os
import hmac
import hashlib
import time
import sys
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv

# Assuming your local 'common' module is available in the PYTHONPATH
from common.logging import get_configured_logger

# Load .env file for local development
load_dotenv()

app = Flask(__name__)
logger = get_configured_logger("main")


def get_env_or_fail(var_name):
    value = os.environ.get(var_name)
    if not value:
        logger.error(f"Required environment variable '{var_name}' is not set.")
        sys.exit(1)
    return value


# Validate config on startup
SLACK_SIGNING_SECRET = get_env_or_fail("SLACK_SIGNING_SECRET")
SLACK_BOT_TOKEN = get_env_or_fail("SLACK_BOT_TOKEN")
TARGET_CHANNEL_ID = get_env_or_fail("TARGET_CHANNEL_ID")


def verify_slack_signature(headers, body):
    timestamp = headers.get("X-Slack-Request-Timestamp")
    signature = headers.get("X-Slack-Signature")

    if not timestamp or not signature:
        logger.warning("Missing Slack signature headers.")
        return False

    # Check for replay attacks
    if abs(time.time() - int(timestamp)) > 60 * 5:
        logger.warning("Slack request timestamp is too old.")
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

    is_valid = hmac.compare_digest(my_sig, signature)
    if not is_valid:
        logger.error("Signature verification failed.")
    return is_valid


@app.route("/slack/ingress", methods=["POST"])
def slack_ingress():
    raw_data = request.get_data()
    data = request.json

    # 1. URL Verification Handshake
    # We do this BEFORE the signature check to ensure the Slack App Dashboard
    # can always verify the endpoint during initial setup.
    if data and data.get("type") == "url_verification":
        logger.info("Handling Slack URL verification challenge.")
        return jsonify({"challenge": data.get("challenge")})

    # 2. Signature Verification
    if not verify_slack_signature(request.headers, raw_data):
        return "Unauthorized", 403

    # 3. Event Processing
    event = data.get("event", {})

    # Log every event received for debugging
    logger.info(
        f"Received event: {event.get('type')} in channel: {event.get('channel')}"
    )

    # Check for:
    # - Standard 'message' type
    # - Correct Channel ID (filtered in code)
    # - Not a bot message (prevents infinite loops)
    if (
        event.get("type") == "message"
        and event.get("channel") == TARGET_CHANNEL_ID
        and "bot_id" not in event
        and event.get("subtype") is None  # Ignore edits, joins, etc.
    ):
        user_text = event.get("text", "").strip().lower()
        logger.info(
            f"Processing message: '{user_text}' from channel {event.get('channel')}"
        )

        if user_text == "hi":
            logger.info("Triggering 'hi' response.")
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={"channel": TARGET_CHANNEL_ID, "text": "you typed 'hi'"},
            )
            if not resp.json().get("ok"):
                logger.error(f"Slack API Error: {resp.json().get('error')}")

    return "OK", 200


if __name__ == "__main__":
    # Cloud Run provides the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

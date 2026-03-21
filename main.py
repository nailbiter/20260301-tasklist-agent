import os
import hmac
import hashlib
import time
import sys
from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv
import logging

from common.logging import get_configured_logger

# Load .env file for local development
load_dotenv()

app = Flask(__name__)

logger = get_configured_logger("main")


def get_env_or_fail(var_name):
    value = os.environ.get(var_name)
    if not value:
        print(f"ERROR: Required environment variable '{var_name}' is not set.")
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
        return False
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


@app.route("/slack/ingress", methods=["POST"])
def slack_ingress():
    raw_data = request.get_data()
    if not verify_slack_signature(request.headers, raw_data):
        return "Unauthorized", 403

    data = request.json

    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    event = data.get("event", {})

    logger.debug(dict(event=event))

    # Logic: Only respond to "hi" in the specific channel, ignoring other bots
    if (
        event.get("type") == "message"
        and event.get("channel") == TARGET_CHANNEL_ID
        and "bot_id" not in event
    ):
        user_text = event.get("text", "").strip().lower()

        if user_text == "hi":
            requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={"channel": TARGET_CHANNEL_ID, "text": "you typed 'hi'"},
            )

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

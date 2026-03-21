import imaplib
import email
from email.header import decode_header
import datetime
import os
import json
import uuid
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.cloud import firestore
from utils import get_configured_logger

# Load environment variables
load_dotenv()

# Initialize Firestore
db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))

# ---------------------------------------------------------------------------
# Session Management (Firestore)
# ---------------------------------------------------------------------------


def load_chat_history(session_id: str) -> list:
    """Loads the conversation history for a given session from Firestore."""
    doc_ref = db.collection("mail_sessions").document(session_id)
    doc = doc_ref.get()
    if doc.exists:
        # Firestore returns dicts, we need to convert them back to types.Content
        history_data = doc.to_dict().get("history", [])
        contents = []
        for content_dict in history_data:
            parts = []
            for part_dict in content_dict.get("parts", []):
                if "text" in part_dict:
                    parts.append(types.Part.from_text(text=part_dict["text"]))
                elif "function_call" in part_dict:
                    fc = part_dict["function_call"]
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=fc["name"], args=fc["args"]
                            )
                        )
                    )
                elif "function_response" in part_dict:
                    fr = part_dict["function_response"]
                    parts.append(
                        types.Part.from_function_response(
                            name=fr["name"], response=fr["response"]
                        )
                    )
            contents.append(types.Content(role=content_dict["role"], parts=parts))
        return contents
    return []


def save_chat_history(session_id: str, contents: list):
    """Saves the conversation history to Firestore."""
    history_data = []
    for content in contents:
        parts_data = []
        for part in content.parts:
            if part.text:
                parts_data.append({"text": part.text})
            elif part.function_call:
                parts_data.append(
                    {
                        "function_call": {
                            "name": part.function_call.name,
                            "args": part.function_call.args,
                        }
                    }
                )
            elif part.function_response:
                parts_data.append(
                    {
                        "function_response": {
                            "name": part.function_response.name,
                            "response": part.function_response.response,
                        }
                    }
                )
        history_data.append({"role": content.role, "parts": parts_data})

    doc_ref = db.collection("mail_sessions").document(session_id)
    doc_ref.set({"history": history_data, "updated_at": firestore.SERVER_TIMESTAMP})


# ---------------------------------------------------------------------------
# Tool Definitions (These will be exposed to Gemini)
# ---------------------------------------------------------------------------


def get_imap_client():
    server = os.getenv("IMAP_SERVER")
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    if not all([server, user, password]):
        raise ValueError(
            "Missing email configuration (IMAP_SERVER, EMAIL_USER, EMAIL_PASSWORD)"
        )
    mail = imaplib.IMAP4_SSL(server)
    mail.login(user, password)
    return mail


def read_recent_emails(folder: str = "INBOX", unread_from: str = None) -> str:
    """
    Retrieves unread emails from the mailbox starting from yesterday 0am [default] or predefined start period.

    Args:
        folder: The mailbox folder to read from (default: "INBOX").
        unread_from: date in "%Y-%m-%d" from which to start load unread emails (default = yesterday)
    """
    logger = get_configured_logger("read_recent_emails", level="DEBUG")
    print(
        f"[Tool Execution] Reading recent emails from {dict(folder=folder,unread_from=unread_from)}..."
    )

    try:
        mail = get_imap_client()
        mail.select(folder)

        # Yesterday's date for SINCE (format: 01-Jan-2023)
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        since_date = (
            yesterday
            if unread_from is None
            else datetime.datetime.strptime(unread_from, "%Y-%m-%d")
        ).strftime("%d-%b-%Y")

        # Search for unread emails since yesterday
        ## FIXME: which timezone is this?
        status, data = mail.uid("search", None, f'(UNSEEN SINCE "{since_date}")')
        if status != "OK":
            return json.dumps({"error": f"Search failed: {status}"})

        uids = data[0].split()
        emails = []
        for uid in uids:
            # Fetch specific fields: SUBJECT, FROM, DATE
            status, msg_data = mail.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])"
            )
            if status != "OK":
                continue

            # msg_data[0] is typically a tuple: (b'UID ...', b'Subject: ...\r\nFrom: ...')
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue

            raw_header = msg_data[0][1].decode("utf-8", errors="ignore")
            msg = email.message_from_string(raw_header)

            subject, encoding = decode_header(msg.get("Subject", ""))[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8")

            from_, encoding = decode_header(msg.get("From", ""))[0]
            if isinstance(from_, bytes):
                from_ = from_.decode(encoding or "utf-8")

            date = msg.get("Date", "")

            emails.append(
                {
                    "uid": uid.decode("utf-8"),
                    "subject": subject,
                    "from": from_,
                    "date": date,
                }
            )

        mail.logout()
        logger.debug(dict(len_emails=len(emails)))
        return json.dumps(emails)
    except Exception as e:
        logger.error(e)
        return json.dumps({"error": f"Failed to read emails: {str(e)}"})


def mark_as_read(msg_ids: list[str], folder: str = "INBOX") -> str:
    """
    Marks the specified emails as read.

    Args:
        msg_ids: A list of message UIDs to mark as read.
        folder: The mailbox folder where the emails are located (default: "INBOX").
    """
    logger = get_configured_logger("mark_as_read", level="DEBUG")
    print(f"[Tool Execution] Marking emails as read: {msg_ids}...")

    try:
        mail = get_imap_client()
        mail.select(folder)
        uids = ",".join(msg_ids)
        status, _ = mail.uid("store", uids, "+FLAGS", r"(\Seen)")
        mail.logout()
        if status == "OK":
            return json.dumps({"success": True})
        return json.dumps({"error": f"Failed to mark as read: {status}"})
    except Exception as e:
        logger.error(e)
        return json.dumps({"error": f"Failed to mark as read: {str(e)}"})


def label_emails(msg_ids: list[str], label: str, folder: str = "INBOX") -> str:
    """
    Labels the specified emails with a given label (Gmail-specific).

    Args:
        msg_ids: A list of message UIDs to label.
        label: The label to apply (e.g., "Work", "Archive").
        folder: The mailbox folder where the emails are located (default: "INBOX").
    """
    logger = get_configured_logger("label_emails", level="DEBUG")
    print(f"[Tool Execution] Labeling emails {msg_ids} with label '{label}'...")

    try:
        mail = get_imap_client()
        mail.select(folder)
        uids = ",".join(msg_ids)
        # Gmail IMAP supports X-GM-LABELS
        status, _ = mail.uid("store", uids, "+X-GM-LABELS", f'"{label}"')
        mail.logout()
        if status == "OK":
            return json.dumps({"success": True})
        return json.dumps({"error": f"Failed to label emails: {status}"})
    except Exception as e:
        logger.error(e)
        return json.dumps({"error": f"Failed to label emails: {str(e)}"})


# ---------------------------------------------------------------------------
# Agent Setup & Execution
# ---------------------------------------------------------------------------

logger = get_configured_logger("agent-mailmaster", level="INFO")
request_count = 0


def ask_agent(prompt: str, session_id: str = None) -> str:
    """
    Main function to initialize the Gemini client, bind tools, and generate a response.
    Loads and saves conversation history to/from Firestore for session persistence.

    Args:
        prompt: The user query.
        session_id: A unique ID for the session. If None, a new UUID is generated.

    Returns:
        The session_id used for this interaction.
    """
    global request_count

    if session_id is None:
        session_id = f"mail_{uuid.uuid4()}"
        print(f"[New Session Created] Session ID: {session_id}")
    else:
        if not session_id.startswith("mail_"):
            session_id = f"mail_{session_id}"
        print(f"[Existing Session] Session ID: {session_id}")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return session_id

    api_key = api_key.strip("'\"")
    client = genai.Client(
        api_key=api_key,
        project=os.environ["GENAI_GOOGLE_CLOUD_PROJECT"],
    )

    try:
        with open("system_message_mail.md", "r") as f:
            system_instruction = f.read()
    except FileNotFoundError:
        system_instruction = "You are a helpful email-management assistant."

    today = datetime.date.today().strftime("%Y-%m-%d")

    # 1. Load existing session history
    contents = load_chat_history(session_id)

    # 2. Add current user prompt
    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=f"Today's date is {today}. User query: {prompt}"
                )
            ],
        )
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[
            read_recent_emails,
            mark_as_read,
            label_emails,
        ],
        temperature=0.2,
    )

    print(f"User: {prompt}\n")
    print("Agent is thinking...\n---")

    while True:
        request_count += 1
        logger.info(f"Making request #{request_count} to model...")

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=contents,
            config=config,
        )

        # Add the model's response to the conversation history
        contents.append(response.candidates[0].content)

        # Check if there are any tool calls
        tool_calls = [
            part.function_call
            for part in response.candidates[0].content.parts
            if part.function_call
        ]

        if not tool_calls:
            break

        # Process each tool call
        tool_responses = []
        for tool_call in tool_calls:
            function_name = tool_call.name
            args = tool_call.args

            # Dispatch to the correct function
            if function_name == "read_recent_emails":
                result = read_recent_emails(**args)
            elif function_name == "mark_as_read":
                result = mark_as_read(**args)
            elif function_name == "label_emails":
                result = label_emails(**args)
            else:
                result = json.dumps({"error": f"Unknown tool: {function_name}"})

            tool_responses.append(
                types.Part.from_function_response(
                    name=function_name, response={"result": result}
                )
            )

        # Add tool results to the conversation history
        contents.append(types.Content(role="user", parts=tool_responses))

    # 3. Save the updated history back to Firestore
    save_chat_history(session_id, contents)

    print("---\nResponse:")
    print(response.text)
    return session_id


if __name__ == "__main__":
    import sys

    # To test switching:
    #   python agent-mailmaster.py "Prompt" "optional_uuid"
    user_prompt = "Read my recent emails and tell me if there's anything urgent."
    provided_session_id = None

    if len(sys.argv) > 1:
        user_prompt = sys.argv[1]
    if len(sys.argv) > 2:
        provided_session_id = sys.argv[2]

    ask_agent(user_prompt, session_id=provided_session_id)

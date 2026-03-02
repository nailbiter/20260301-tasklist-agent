import imaplib
import email
from email.header import decode_header
import datetime
import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
from utils import get_configured_logger

# Load environment variables
load_dotenv()

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


def read_recent_emails(folder: str = "INBOX") -> str:
    """
    Retrieves unread emails from the mailbox starting from yesterday 0am.

    Args:
        folder: The mailbox folder to read from (default: "INBOX").
    """
    logger = get_configured_logger("read_recent_emails", level="DEBUG")
    print(f"[Tool Execution] Reading recent emails from {folder}...")

    try:
        mail = get_imap_client()
        mail.select(folder)

        # Yesterday's date for SINCE (format: 01-Jan-2023)
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        since_date = yesterday.strftime("%d-%b-%Y")

        # Search for unread emails since yesterday
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


def ask_agent(prompt: str) -> None:
    """
    Main function to initialize the Gemini client, bind tools, and generate a response.
    """
    global request_count
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in environment.")
        return

    api_key = api_key.strip("'\"")
    client = genai.Client(api_key=api_key)

    try:
        with open("system_message_mail.md", "r") as f:
            system_instruction = f.read()
    except FileNotFoundError:
        system_instruction = "You are a helpful email-management assistant."

    today = datetime.date.today().strftime("%Y-%m-%d")
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=f"Today's date is {today}. User query: {prompt}"
                )
            ],
        )
    ]

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[read_recent_emails, mark_as_read, label_emails],
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

    print("---\nResponse:")
    print(response.text)


if __name__ == "__main__":
    ask_agent("Read my recent emails and tell me if there's anything urgent.")

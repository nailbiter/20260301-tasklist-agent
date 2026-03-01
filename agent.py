import os
import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Tool Definitions (These will be exposed to Gemini)
# ---------------------------------------------------------------------------

import json
import requests
from requests.auth import HTTPBasicAuth
from pymongo import MongoClient

def get_jira_tasks(assignee: str = "me", status: str = "To Do") -> str:
    """
    Retrieves tasks from Jira based on assignee and status.
    
    Args:
        assignee: The person assigned to the task (default: "me").
        status: The current status of the task (e.g., "To Do", "In Progress", "Done").
    """
    jira_url = os.getenv("JIRA_URL")
    jira_user = os.getenv("JIRA_USER")
    jira_api_token = os.getenv("JIRA_API_TOKEN")

    if not all([jira_url, jira_user, jira_api_token]):
        return json.dumps({"error": "Jira environment variables are not fully configured."})

    # Construct the JQL query
    assignee_query = "currentUser()" if assignee == "me" else f'"{assignee}"'
    jql = f'assignee = {assignee_query} AND status = "{status}"'

    print(f"[Tool Execution] Fetching Jira tasks for '{assignee}' with status '{status}' using JQL: {jql}...")
    
    try:
        url = f"{jira_url.rstrip('/')}/rest/api/3/search"
        auth = HTTPBasicAuth(jira_user, jira_api_token)
        headers = {"Accept": "application/json"}
        params = {"jql": jql, "maxResults": 10}

        response = requests.get(url, headers=headers, params=params, auth=auth)
        response.raise_for_status()
        
        data = response.json()
        tasks = []
        for issue in data.get("issues", []):
            tasks.append({
                "id": issue["key"],
                "title": issue["fields"].get("summary"),
                "priority": issue["fields"].get("priority", {}).get("name"),
                "status": issue["fields"].get("status", {}).get("name"),
                "url": f"{jira_url.rstrip('/')}/browse/{issue['key']}"
            })
        
        return json.dumps(tasks)

    except Exception as e:
        return json.dumps({"error": f"Failed to fetch Jira tasks: {str(e)}"})

def get_mongo_tasks(priority: str = "High", due_today: bool = True) -> str:
    """
    Retrieves personal tasks from the custom MongoDB database.
    
    Args:
        priority: The priority level of the task (e.g., "High", "Medium", "Low").
        due_today: Boolean indicating if only tasks due today should be returned.
    """
    mongo_uri = os.getenv("MONGO_URI")
    mongo_db_name = os.getenv("MONGO_DB_NAME")
    
    if not mongo_uri:
        return json.dumps({"error": "MONGO_URI environment variable is not configured."})

    print(f"[Tool Execution] Fetching Mongo tasks (Priority: {priority}, Due Today: {due_today})...")
    
    try:
        client = MongoClient(mongo_uri)
        
        # Determine database and collection
        if mongo_db_name:
            db = client[mongo_db_name]
            collection = db["gstasks.tasks"]
        else:
            db = client["gstasks"]
            collection = db["tasks"]

        query = {"priority": priority}
        if due_today:
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            # Support both string format and potentially datetime (though JQL-like agents often use strings)
            # We'll stick to string for now as it's common in simple task stores
            query["due"] = today_str

        cursor = collection.find(query).limit(20)
        tasks = []
        for doc in cursor:
            # Convert ObjectId and datetime to string for JSON serialization
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            if "due" in doc and isinstance(doc["due"], datetime.datetime):
                doc["due"] = doc["due"].strftime("%Y-%m-%d")
            tasks.append(doc)
        
        client.close()
        return json.dumps(tasks)

    except Exception as e:
        return json.dumps({"error": f"Failed to fetch Mongo tasks: {str(e)}"})

# ---------------------------------------------------------------------------
# Agent Setup & Execution
# ---------------------------------------------------------------------------

def ask_agent(prompt: str) -> None:
    """
    Main function to initialize the Gemini client, bind tools, and generate a response.
    """
    # The SDK automatically picks up GEMINI_API_KEY from the environment
    client = genai.Client()
    
    # Read the system prompt from GEMINI.md
    try:
        with open("GEMINI.md", "r") as f:
            system_instruction = f.read()
    except FileNotFoundError:
        system_instruction = "You are a helpful task-management assistant."

    today = datetime.date.today().strftime("%Y-%m-%d")
    full_prompt = f"Today's date is {today}. User query: {prompt}"

    # Configure the model to use our defined functions as tools
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[get_jira_tasks, get_mongo_tasks],
        temperature=0.2, # Low temperature for factual task retrieval
    )

    print(f"User: {prompt}\n")
    print("Agent is thinking...\n---")
    
    # Using gemini-2.0-flash as it excels at complex tool calling and reasoning
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=full_prompt,
        config=config,
    )
    
    print("---\nResponse:")
    print(response.text)

if __name__ == "__main__":
    # Fallback for direct execution testing
    ask_agent("What are my most important tasks today?")

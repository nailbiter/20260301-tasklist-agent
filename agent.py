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

def get_jira_tasks(assignee: str = "me", status: str = "To Do") -> str:
    """
    Retrieves tasks from Jira based on assignee and status.
    
    Args:
        assignee: The person assigned to the task (default: "me").
        status: The current status of the task (e.g., "To Do", "In Progress", "Done").
    """
    # TODO: Implement actual Jira API call using requests or jira-python
    # Requires: os.getenv("JIRA_URL"), os.getenv("JIRA_USER"), os.getenv("JIRA_API_TOKEN")
    print(f"[Tool Execution] Fetching Jira tasks for '{assignee}' with status '{status}'...")
    
    # Mock return data
    return '[{"id": "PROJ-123", "title": "Review PR for ML pipeline", "priority": "High"}]'

def get_mongo_tasks(priority: str = "High", due_today: bool = True) -> str:
    """
    Retrieves personal tasks from the custom MongoDB database.
    
    Args:
        priority: The priority level of the task (e.g., "High", "Medium", "Low").
        due_today: Boolean indicating if only tasks due today should be returned.
    """
    # TODO: Implement actual pymongo queries
    # Requires: os.getenv("MONGO_URI"), os.getenv("MONGO_DB_NAME")
    print(f"[Tool Execution] Fetching Mongo tasks (Priority: {priority}, Due Today: {due_today})...")
    
    # Mock return data
    return '[{"task": "Buy groceries", "priority": "High", "due": "Today"}]'

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
    
    # Using gemini-2.5-pro as it excels at complex tool calling and reasoning
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=full_prompt,
        config=config,
    )
    
    print("---\nResponse:")
    print(response.text)

if __name__ == "__main__":
    # Fallback for direct execution testing
    ask_agent("What are my most important tasks today?")

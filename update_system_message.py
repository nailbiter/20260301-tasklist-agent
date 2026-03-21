import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def update_system_message(agent_id="taskmaster", file_path="system_message_taskmaster.md"):
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("Error: MONGO_URI not found in environment.")
        sys.exit(1)

    try:
        with open(file_path, "r") as f:
            system_instruction = f.read()
    except FileNotFoundError:
        print(f"Error: {file_path} not found.")
        sys.exit(1)

    try:
        client = MongoClient(mongo_uri)
        db = client["logistics"]
        collection = db["agent_configs"]

        result = collection.update_one(
            {"agent_id": agent_id},
            {"$set": {"system_instruction": system_instruction}},
            upsert=True
        )

        if result.matched_count > 0:
            print(f"Successfully updated system instruction for '{agent_id}' in MongoDB.")
        else:
            print(f"Successfully created new system instruction for '{agent_id}' in MongoDB.")
        
        client.close()
    except Exception as e:
        print(f"Error updating MongoDB: {e}")
        sys.exit(1)

if __name__ == "__main__":
    update_system_message()

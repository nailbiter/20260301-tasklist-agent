import os
import sys
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables (as in the agent)
load_dotenv()


def check_connection(insecure=False):
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("Error: MONGO_URI not set in .env")
        sys.exit(1)

    print(f"Connecting to: {mongo_uri}")

    # Configure options
    client_kwargs = {}
    if insecure:
        print(
            "!! Using insecure SSL configuration (tlsAllowInvalidCertificates=True) !!"
        )
        client_kwargs["tlsAllowInvalidCertificates"] = True
        client_kwargs["tlsAllowInvalidHostnames"] = True

    try:
        # Connect
        client = MongoClient(mongo_uri, **client_kwargs, serverSelectionTimeoutMS=5000)

        # Ping the server to verify connection
        client.admin.command("ping")
        print("SUCCESS: Connected to MongoDB.")
        client.close()
    except Exception as e:
        print(f"FAILED: Connection error:\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    insecure = "--insecure" in sys.argv
    check_connection(insecure)

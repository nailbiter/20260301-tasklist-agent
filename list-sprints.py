#!/usr/bin/env python
"""===============================================================================

        FILE: /Users/nailbiter/for/for-jira-playground/scripts/list-sprints.py

       USAGE: (not intended to be directly executed)

 DESCRIPTION: 

     OPTIONS: ---
REQUIREMENTS: ---
        BUGS: ---
       NOTES: ---
      AUTHOR: Alex Leontiev (alozz1991@gmail.com)
ORGANIZATION: 
     VERSION: ---
     CREATED: 2025-11-02T12:14:59.651120
    REVISION: ---

==============================================================================="""
from os import environ
import logging
from datetime import datetime, timedelta, date

from alex_leontiev_toolbox_python.utils.logging_helpers import get_configured_logger
from jira import JIRA
from dotenv import load_dotenv
import pandas as pd
import tqdm

load_dotenv(override=True)
# logging.basicConfig(level=logging.DEBUG)
logger = get_configured_logger("list-sprints", level="DEBUG")

jira_server = environ["JIRA_URL"]  # e.g., "https://yourcompany.atlassian.net"
if not jira_server.startswith("https://"):
    jira_server = "https://" + jira_server
jira_username = environ["JIRA_EMAIL"]
jira_api_token = environ[
    "JIRA_API_TOKEN"
]  # Generate an API token in your Atlassian account settings

try:
    # logging.getLogger("jira").setLevel(logging.DEBUG)
    # logging.getLogger('requests').setLevel(logging.DEBUG)
    jira = JIRA(server=jira_server, basic_auth=(jira_username, jira_api_token))
except Exception as e:
    logger.error(e)
    raise e

board_id = environ["JIRA_BOARD_ID"]  # Replace with your board ID

# Get all sprints for a specific board
sprints = jira.sprints(board_id=board_id, state="active,future")

# Iterate and print sprint details
# for sprint in sprints:
#     print(f"Sprint ID: {sprint.id}")
#     print(f"Sprint Name: {sprint.name}")
#     print(f"Sprint State: {sprint.state}")  # e.g., 'future', 'active', 'closed'
#     print(f"Start Date: {sprint.startDate}")
#     print(f"End Date: {sprint.endDate}")
#     print("-" * 20)
df_sprints = pd.DataFrame(
    [
        {
            k: getattr(sprint, k) if hasattr(sprint, k) else None
            for k in ["id", "name", "state", "startDate", "endDate"]
        }
        for sprint in sprints
        # in tqdm.tqdm(sprints)
    ]
)
for k in ["startDate", "endDate"]:
    df_sprints[k] = pd.to_datetime(df_sprints[k])
df_sprints.sort_values(by=["name", "id"], inplace=True, ignore_index=True)
df_sprints["is_past"] = (
    df_sprints["name"]
    .str[:10]
    .le(datetime.now().strftime("%Y-%m-%d"))
    .apply(str)
    .replace({"True": "x", "False": ""})
)
print(df_sprints.to_string())

#!/bin/bash

# Configuration
PROJECT_ID="api-project-424250507607"
REGION="us-east1"
SERVICE_NAME="slack-echo-middleware"

# Ensure local .env variables are exported for the gcloud command
# This assumes you have a .env file in the same directory
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "Deploying $SERVICE_NAME to $REGION..."

gcloud run deploy $SERVICE_NAME \
  --source . \
  --project $PROJECT_ID \
  --region $REGION \
  --set-env-vars="SLACK_SIGNING_SECRET=$SLACK_SIGNING_SECRET,SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN,TARGET_CHANNEL_ID=$TARGET_CHANNEL_ID,GEMINI_API_KEY=$GEMINI_API_KEY,JIRA_URL=$JIRA_URL,JIRA_EMAIL=$JIRA_EMAIL,JIRA_API_TOKEN=$JIRA_API_TOKEN,JIRA_BOARD_ID=$JIRA_BOARD_ID,MONGO_DB_NAME=$MONGO_DB_NAME,GOOGLE_CLOUD_PROJECT=$PROJECT_ID" \
  --set-secrets="MONGO_URI=mongo-url-s8:latest,FOR_METADATA_MONGO_URI=mongo-url-gaq:latest" \
  --allow-unauthenticated

# Output the URL to paste into Slack App Dashboard
echo "--- Deployment Complete ---"
gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format 'value(status.url)'

## update system message, just in case
./update_system_message.py

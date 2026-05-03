#!/bin/bash
set -e

# Configuration
REGION="us-east1"

# Ensure local .env variables are exported for the gcloud command
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Resolve symlink so the Docker build context can COPY the system message template
cp -L system_message_taskmaster.jinja.md _system_message_taskmaster.jinja.md
trap 'rm -f _system_message_taskmaster.jinja.md' EXIT

echo "Deploying $SERVICE_NAME to $REGION..."

gcloud run deploy $SERVICE_NAME \
  --source . \
  --project $PROJECT_ID \
  --region $REGION \
  --set-env-vars="SLACK_SIGNING_SECRET=$SLACK_SIGNING_SECRET,SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN,TARGET_CHANNEL_ID=$TARGET_CHANNEL_ID,GEMINI_API_KEY=$GEMINI_API_KEY,JIRA_URL=$JIRA_URL,JIRA_EMAIL=$JIRA_EMAIL,JIRA_API_TOKEN=$JIRA_API_TOKEN,JIRA_BOARD_ID=$JIRA_BOARD_ID,MONGO_DB_NAME=$MONGO_DB_NAME,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,IS_LANGGRAPH_DEV=0,FOR_METADATA_MONGO_URI=$FOR_METADATA_MONGO_URI" \
  --set-secrets="MONGO_URI=mongo-url-s8:latest" \
  --allow-unauthenticated

echo "--- Deployment Complete ---"
gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format 'value(status.url)'
echo "$(date '+%Y-%m-%d %H:%M:%S') deployed $SERVICE_NAME" >> deploy.log

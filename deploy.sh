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
  --set-env-vars="SLACK_SIGNING_SECRET=$SLACK_SIGNING_SECRET,SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN,TARGET_CHANNEL_ID=$TARGET_CHANNEL_ID" \
  --allow-unauthenticated

# Output the URL to paste into Slack App Dashboard
echo "--- Deployment Complete ---"
gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --format 'value(status.url)'
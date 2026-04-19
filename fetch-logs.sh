#!/bin/bash
set -e

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

gcloud run services logs read "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region us-east1 \
    >> service.log

echo "Logs appended to service.log"

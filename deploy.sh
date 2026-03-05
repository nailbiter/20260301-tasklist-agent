#!/bin/sh

if [ -z "$GITHUB_TOKEN" ]; then
  echo "Error: GITHUB_TOKEN environment variable is not set."
  exit 1
fi

# Make sure you are in the directory with your files
gcloud run deploy notebook-report-job \
    --source . \
    --region us-east1 \
    --no-allow-unauthenticated \
    --timeout=600 \
    --set-env-vars=GITHUB_TOKEN=$GITHUB_TOKEN \
    --set-secrets="MONGO_URL=mongo-url-gaq:latest"

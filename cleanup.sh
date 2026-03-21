#!/bin/bash

# Configuration
PROJECT_ID="api-project-424250507607"
REGION="us-east1"
REPO_NAME="cloud-run-source-deploy"
IMAGE_NAME="slack-echo-middleware"

FULL_IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}"

echo "Fetching images for ${IMAGE_NAME}..."

# List all versions of the image, sorted by creation time (descending)
# We use --format to get the digest and --sort-by to ensure newest is first
# tail -n +2 skips the first (latest) entry
DIGESTS_TO_DELETE=$(gcloud artifacts docker images list "$FULL_IMAGE_NAME" \
    --project="$PROJECT_ID" \
    --format='value(DIGEST)' \
    --sort-by="~CREATE_TIME" | tail -n +2)

if [ -z "$DIGESTS_TO_DELETE" ]; then
    echo "No old images found to delete (only 1 or 0 versions exist)."
    exit 0
fi

echo "The following digests will be deleted:"
echo "$DIGESTS_TO_DELETE"

# Count the number of digests to delete
COUNT=$(echo "$DIGESTS_TO_DELETE" | wc -l | xargs)

read -p "Are you sure you want to delete these $COUNT images? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[yY]$ ]]; then
    echo "Cleanup aborted."
    exit 0
fi

for DIGEST in $DIGESTS_TO_DELETE; do
    echo "Deleting ${IMAGE_NAME}@${DIGEST}..."
    # Using full command on one line for robustness
    gcloud artifacts docker images delete "${FULL_IMAGE_NAME}@${DIGEST}" --project="$PROJECT_ID" --quiet --delete-tags
done

echo "Cleanup complete."

import logging
import os
import tempfile
import typing
from datetime import datetime

import nbconvert
import papermill
import requests
from fastapi import FastAPI, HTTPException, Response
from google.cloud import storage

# --- Configuration ---
# Set the target URL for the final notification
NOTIFY_SERVICE_URL = "https://send-telegram-message-callback-3cn7gmyvoq-ue.a.run.app"
# GCS Configuration
GCS_BUCKET_NAME = "20251116-for-public-files"
GCS_BLOB_PREFIX = "html/weekly-reports"
# Notebook Configuration
INPUT_NOTEBOOK = "notebook.ipynb"
GITHUB_REPO_OWNER = os.environ.get("GITHUB_REPO_OWNER", "nailbiter")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME", "20251116-money-cloud-run")
GITHUB_REPO_BRANCH = os.environ.get("GITHUB_REPO_BRANCH", "main")
GITHUB_NOTEBOOK_PATH = os.environ.get("GITHUB_NOTEBOOK_PATH", "notebook.ipynb")
GITHUB_TOKEN_SECRET_NAME = os.environ.get(
    "GITHUB_TOKEN_SECRET_NAME",
    "projects/your-gcp-project-id/secrets/github-token/versions/latest",
)

# --- Initialization ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
app = FastAPI(
    title="Notebook Report Generator",
    description="Runs a notebook, uploads it to GCS, and sends a notification.",
)
storage_client = storage.Client()


# --- Google Auth Helper ---
# This function is copied from your provided example to fetch an ID token.
def get_id_token(audience_url: str) -> typing.Optional[str]:
    """Fetches a Google-signed ID token for the given audience URL."""
    token_url = f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience={audience_url}"
    token_headers = {"Metadata-Flavor": "Google"}
    try:
        token_response = requests.get(token_url, headers=token_headers)
        token_response.raise_for_status()  # Raise an exception for bad status codes
        return token_response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch ID token for {audience_url}: {e}")
        return None


def get_github_token() -> typing.Optional[str]:
    """Fetches the GitHub token from Google Cloud Secret Manager."""
    from google.cloud import secretmanager

    # try:
    #     client = secretmanager.SecretManagerServiceClient()
    #     response = client.access_secret_version(name=GITHUB_TOKEN_SECRET_NAME)
    #     return response.payload.data.decode("UTF-8")
    # except Exception as e:
    #     logging.error(f"Failed to access GitHub token from Secret Manager: {e}")
    #     return None
    return os.environ["GITHUB_TOKEN"]


# # --- API Endpoints ---
# @app.get("/")
# async def health_check():
#     """A simple health check endpoint."""
#     return {"status": "ok"}


# @app.post("/run-report")
@app.post("/")
async def run_report_job():
    """
    Triggers the full report generation and notification process.
    """
    notebook_to_execute = INPUT_NOTEBOOK
    github_notebook_used = False
    fallback_reason = "No attempt to fetch from GitHub"
    temp_github_notebook_path = None

    try:
        # Attempt to fetch GitHub token
        github_token = get_github_token()
        if github_token:
            github_raw_url = (
                f"https://raw.githubusercontent.com/{GITHUB_REPO_OWNER}/"
                f"{GITHUB_REPO_NAME}/{GITHUB_REPO_BRANCH}/{GITHUB_NOTEBOOK_PATH}"
            )
            logging.info(f"Attempting to fetch notebook from GitHub: {github_raw_url}")
            headers = {"Authorization": f"token {github_token}"}

            try:
                response = requests.get(github_raw_url, headers=headers, timeout=10)
                response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

                # Save the fetched notebook to a temporary file
                temp_file = tempfile.NamedTemporaryFile(
                    mode="w", delete=False, suffix=".ipynb"
                )
                temp_file.write(response.text)
                temp_file.close()
                temp_github_notebook_path = temp_file.name

                notebook_to_execute = temp_github_notebook_path
                github_notebook_used = True
                fallback_reason = "Successfully fetched from GitHub"
                logging.info(
                    f"Successfully fetched notebook from GitHub. Using temporary file: {temp_github_notebook_path}"
                )

            except requests.exceptions.RequestException as e:
                logging.error(
                    f"Failed to fetch notebook from GitHub: {e}. Falling back to local notebook.",
                    exc_info=True,
                )
                fallback_reason = f"GitHub fetch failed: {e}"
            except Exception as e:
                logging.error(
                    f"An unexpected error occurred during GitHub notebook processing: {e}. Falling back to local notebook.",
                    exc_info=True,
                )
                fallback_reason = f"GitHub processing error: {e}"
        else:
            logging.warning(
                "GitHub token not available. Falling back to local notebook."
            )
            fallback_reason = "GitHub token not available"

        # Use a temporary directory to manage intermediate files
        with tempfile.TemporaryDirectory() as temp_dir:
            date_str = datetime.now().strftime("%Y%m%d")
            report_filename = f"{date_str}-weekly-report.html"

            executed_notebook_path = os.path.join(temp_dir, "executed.ipynb")
            html_output_path = os.path.join(temp_dir, report_filename)

            # --- 1. Run the notebook with Papermill ---
            logging.info(f"Executing notebook: {notebook_to_execute}...")
            try:
                papermill.execute_notebook(notebook_to_execute, executed_notebook_path)
                logging.info(
                    f"Notebook execution complete. Output: {executed_notebook_path}"
                )
            except Exception as e:
                logging.error(f"Papermill execution failed: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail=f"Papermill execution failed: {e}"
                )

            # --- 2. Convert the result to HTML ---
            logging.info(f"Converting notebook to HTML...")
            try:
                exporter = nbconvert.HTMLExporter()
                (body, resources) = exporter.from_filename(executed_notebook_path)

                # Save the HTML body to the output file
                with open(html_output_path, "w", encoding="utf-8") as f:
                    f.write(body)
                logging.info(f"Conversion to HTML complete: {html_output_path}")
            except Exception as e:
                logging.error(f"nbconvert failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"nbconvert failed: {e}")

            # --- 3. Upload the HTML to GCS ---
            logging.info(
                f"Uploading {report_filename} to GCS bucket {GCS_BUCKET_NAME}..."
            )
            try:
                bucket = storage_client.bucket(GCS_BUCKET_NAME)
                blob_path = f"{GCS_BLOB_PREFIX}/{report_filename}"
                blob = bucket.blob(blob_path)

                blob.upload_from_filename(html_output_path)

                # Construct the public URL
                public_url = (
                    f"https://storage.cloud.google.com/{GCS_BUCKET_NAME}/{blob_path}"
                )
                logging.info(f"Upload complete. Public URL: {public_url}")
            except Exception as e:
                logging.error(f"GCS upload failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"GCS upload failed: {e}")

            # --- 4. Call the other Cloud Run function ---
            logging.info(f"Calling notification service at {NOTIFY_SERVICE_URL}...")
            id_token = get_id_token(NOTIFY_SERVICE_URL)

            message_text = f"{public_url} #weeklyReport"
            if not github_notebook_used:
                message_text += (
                    f" (Note: Used local notebook due to: {fallback_reason})"
                )
            else:
                message_text += " (Note: Used latest notebook from GitHub)"

            if not id_token:
                logging.error("Could not get ID token. Skipping notification.")
                # Still return success, as the main task (report gen) worked
                return {
                    "status": "success",
                    "report_url": public_url,
                    "notification": "failed_no_token",
                    "github_notebook_used": github_notebook_used,
                    "fallback_reason": fallback_reason,
                }

            try:
                headers = {"Authorization": f"Bearer {id_token}"}
                payload = {"message": {"text": message_text}}

                response = requests.post(
                    NOTIFY_SERVICE_URL, headers=headers, json=payload
                )
                response.raise_for_status()  # Check for HTTP errors

                logging.info(
                    f"Notification service called successfully. Status: {response.status_code}"
                )
            except requests.exceptions.RequestException as e:
                logging.error(f"Failed to call notification service: {e}")
                # Log the error but don't fail the whole job
                return {
                    "status": "success",
                    "report_url": public_url,
                    "notification": f"failed: {e}",
                    "github_notebook_used": github_notebook_used,
                    "fallback_reason": fallback_reason,
                }

            return {
                "status": "success",
                "report_url": public_url,
                "notification": "sent",
                "github_notebook_used": github_notebook_used,
                "fallback_reason": fallback_reason,
            }

    except HTTPException as http_err:
        # Re-raise HTTP exceptions from our checks
        raise http_err
    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {e}"
        )
    finally:
        # Clean up the temporary GitHub notebook file if it was created
        if temp_github_notebook_path and os.path.exists(temp_github_notebook_path):
            os.remove(temp_github_notebook_path)
            logging.info(
                f"Cleaned up temporary GitHub notebook file: {temp_github_notebook_path}"
            )

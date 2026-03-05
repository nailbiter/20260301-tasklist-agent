# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Set environment variables for Gunicorn
ENV PORT 8080
ENV TIMEOUT 120
ENV WORKER_CLASS "uvicorn.workers.UvicornWorker"
ENV WORKERS 1
ENV LOG_LEVEL "info"

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
# This includes main.py and notebook.ipynb
COPY main.py .
COPY notebook.ipynb .
COPY common.py .

ENV IS_ENSURE_DAY 'Fri'

# Run the web server using Gunicorn
# Gunicorn manages the Uvicorn workers for better stability
CMD exec gunicorn main:app \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WORKERS}" \
    --worker-class "${WORKER_CLASS}" \
    --timeout "${TIMEOUT}" \
    --log-level "${LOG_LEVEL}"

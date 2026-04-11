# Containerizing with `uv`

This guide explains how to create a slim, production-ready Docker image for your LangGraph agents using `uv`.

## Sample Dockerfile

Using a multi-stage approach and `uv sync --no-dev` ensures that development tools (like `langgraph-cli`) are excluded from the final image, minimizing its size and attack surface.

```dockerfile
# 1. Use a slim Python image
FROM python:3.11-slim-bookworm

# 2. Install uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 3. Set the working directory
WORKDIR /app

# 4. Copy ONLY the dependency files first (for better caching)
#    This layer only rebuilds if your dependencies change
COPY pyproject.toml uv.lock ./

# 5. Install PRODUCTION dependencies only
#    --no-dev: Skips langgraph-cli and other dev tools
#    --frozen: Ensures the lockfile is exactly followed
RUN uv sync --frozen --no-dev

# 6. Copy the rest of your application code
COPY . .

# 7. Run your application using 'uv run'
#    This ensures the .venv is used correctly
CMD ["uv", "run", "python", "agent-taskmaster.py"]
```

## Key Benefits

1.  **Tiny Image Size:** By using `--no-dev`, development-only dependencies are never installed in the production environment.
2.  **Deterministic Builds:** The `--frozen` flag ensures that the environment exactly matches your `uv.lock` file.
3.  **Efficient Layer Caching:** By copying `pyproject.toml` and `uv.lock` before the rest of the code, Docker can cache the expensive dependency installation step.
4.  **Speed:** `uv` is significantly faster than `pip` at resolving and installing dependencies during the build process.

## Local Testing
To test the production-style installation locally without dev tools:
```bash
uv sync --no-dev
```

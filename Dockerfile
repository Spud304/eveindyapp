FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first so this layer is cached on code-only changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# Copy source
COPY src/ ./src/

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 5050
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5050", "--preload", "--log-level", "info", "--access-logfile", "-", "--error-logfile", "-", "src.main:app"]

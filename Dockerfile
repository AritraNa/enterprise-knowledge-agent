# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv /uv /uvx /usr/local/bin/

# Install dependencies before application code so dependency layers can be reused.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . ./
RUN uv sync --frozen --no-dev \
    && mkdir -p data/uploads/policies data/uploads/employees

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]

FROM ghcr.io/astral-sh/uv:0.12.15 AS uv

FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --create-home --uid 10001 tomcat
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOMCAT_HOST=0.0.0.0 \
    PORT=8080 \
    TOMCAT_MCP_URL=http://127.0.0.1:8080/mcp/
USER tomcat
EXPOSE 8080
CMD ["tomcat-web-mcp"]

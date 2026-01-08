# Stage 1: Build frontend
FROM node:20-slim AS frontend

WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm install

COPY web/ ./
RUN npm run build

# Stage 2: Python application
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Copy built frontend from stage 1
COPY --from=frontend /app/src/remind/static ./src/remind/static/

# Install the package
RUN uv pip install --system -e .

# Create remind directory for databases (will be overridden by volume mount)
RUN mkdir -p /root/.remind

# Default port (can be overridden via environment variable)
ENV REMIND_PORT=8765

EXPOSE ${REMIND_PORT}

CMD ["sh", "-c", "remind-mcp --host 0.0.0.0 --port ${REMIND_PORT}"]

FROM node:24-alpine AS demo
WORKDIR /demo
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.8
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/src ./src
COPY backend/alembic.ini backend/logging.json ./
COPY backend/migrations ./migrations
COPY --from=demo /demo/dist ./demo
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src" FRAUD_DEMO_DIRECTORY="/app/demo"
RUN useradd --create-home app
USER app
EXPOSE 10000
CMD ["python", "-m", "fraud_api.hosted_start"]

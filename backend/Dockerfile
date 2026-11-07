FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.8
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src ./src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src"
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "fraud_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

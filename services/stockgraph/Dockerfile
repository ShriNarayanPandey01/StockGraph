FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.0
COPY pyproject.toml uv.lock ./
COPY services/upstox/pyproject.toml services/upstox/pyproject.toml
COPY services/stockgraph/pyproject.toml services/stockgraph/pyproject.toml
COPY services/platform/pyproject.toml services/platform/pyproject.toml
COPY services/stockgraph/src services/stockgraph/src
RUN uv sync --frozen --no-dev --no-editable --package stockgraph-service
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "stockgraph.runtime.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

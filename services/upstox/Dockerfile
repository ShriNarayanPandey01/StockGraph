FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.0
COPY pyproject.toml uv.lock ./
COPY services/upstox/pyproject.toml services/upstox/pyproject.toml
COPY services/stockgraph/pyproject.toml services/stockgraph/pyproject.toml
COPY services/platform/pyproject.toml services/platform/pyproject.toml
COPY services/upstox/src services/upstox/src
COPY scripts/populate_sample_stocks.py scripts/populate_sample_stocks.py
RUN uv sync --frozen --no-dev --no-editable --package upstox-service
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8001
CMD ["upstox-api"]

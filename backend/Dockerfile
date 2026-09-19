# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QUANTLAB_DB=/data/quantlab.db \
    QUANTLAB_DB_PATH=/data/quantlab.db

WORKDIR /app

# Install the project plus dev extras (pytest, pyyaml, ...) so the same image
# can serve the API and run the test suite (`python -m pytest -q` from /app).
COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
COPY contracts ./contracts
RUN pip install --no-cache-dir ".[dev]"

VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "quantlab.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

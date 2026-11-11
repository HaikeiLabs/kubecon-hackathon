FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FD_CONCEPTS_PATH=/app/ontology/build/concepts.json \
    FD_SEED_DIR=/app/seed

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY ontology/build ./ontology/build
COPY backend/seed ./seed
RUN pip install --no-cache-dir .

USER 10001:10001
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

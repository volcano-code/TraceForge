# Candidate configuration only: Docker was unavailable during this delivery.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir '.[postgres]' && useradd --uid 10001 --create-home traceforge \
    && mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001:10001
ENV TF_DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["python","-m","uvicorn","traceforge.api:app","--host","0.0.0.0","--port","8000"]

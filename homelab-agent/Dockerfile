FROM python:3.11-slim

WORKDIR /app

# curl for the container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

# kagent BYO contract: the container serves the A2A protocol on :8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "homelab_agent.server:app", "--host", "0.0.0.0", "--port", "8080"]

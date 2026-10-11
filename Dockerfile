# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl is used by the docker-compose healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so code changes don't bust the layer cache.
# The root requirements.txt simply includes the pinned package requirements.
COPY requirements.txt ./
COPY mobile_money_system/requirements.txt ./mobile_money_system/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code + Streamlit theme config.
COPY mobile_money_system ./mobile_money_system
COPY .streamlit ./.streamlit

# The SQLite database lives in /app/data (overridable via MMS_DB_PATH).
ENV MMS_DB_PATH=/app/data/mobile_money.db
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8501 8000

# Default service: the Streamlit web app.
CMD ["streamlit", "run", "mobile_money_system/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.fileWatcherType=none"]

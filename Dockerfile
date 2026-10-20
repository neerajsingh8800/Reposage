FROM python:3.12-slim

# Install system dependencies including git
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY backend/ backend/
COPY ingestion/ ingestion/
COPY sample_repo/ sample_repo/

# Set Python path and environment settings
ENV PYTHONPATH=/app \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Start with a single Uvicorn worker process (process-local LRU cache and conversation memory)
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

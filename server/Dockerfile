# Datang Reader - Docker Image
# Multi-stage build for optimized image size

# Stage 1: Builder
FROM python:3.10-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file (Docker-specific, without GUI dependencies)
COPY requirements.txt .

# Install Python dependencies to a virtual environment
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# Stage 2: Runtime
FROM python:3.10-slim

# Set labels for metadata
LABEL maintainer="Datang Reader Team" \
      description="RFID Attendance Tracking System - HTTP Server Mode" \
      version="1.0.0"

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment to use virtual environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy application code
COPY src/ ./src/
COPY datang_reader.py .

# Create directories for persistent data
RUN mkdir -p /data/logs && \
    chmod 755 /data

# Expose HTTP server port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=2)" || exit 1

# Set default environment variables (can be overridden)
ENV DATANG_API_BASE_URL="" \
    DATANG_READER_USERNAME="" \
    DATANG_READER_PASSWORD="" \
    DATANG_DEVICE_ID=""

# Run HTTP server by default
CMD ["python", "datang_reader.py", "--http-server"]

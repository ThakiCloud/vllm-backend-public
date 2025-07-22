# Multi-stage build for benchmark-vllm service
FROM python:3.10-slim as base

# Set working directory
WORKDIR /app

# Install system dependencies including build tools
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    cmake \
    ninja-build \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables for vLLM
ENV VLLM_TARGET_DEVICE=cpu
ENV CMAKE_BUILD_TYPE=RelWithDebInfo

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create configs directory
RUN mkdir -p configs

# Expose port
EXPOSE 8005

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1

# Run the application
CMD ["python", "main.py"]
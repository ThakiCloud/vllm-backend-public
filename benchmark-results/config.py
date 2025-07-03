"""Configuration settings for the benchmark results storage service."""

import os

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

APP_TITLE = "Benchmark Results Storage Service"
APP_DESCRIPTION = "Service for storing and retrieving benchmark results"
APP_VERSION = "0.1.0"
PORT = 8000

# -----------------------------------------------------------------------------
# MongoDB Configuration
# -----------------------------------------------------------------------------

# Environment-based configuration (recommended for production)
MONGO_URL = os.getenv(
    "MONGO_URL", 
    # Default: With authentication enabled
    "mongodb://admin:password123@mongo-service:27017/?replicaSet=rs0&authSource=admin"
)

# Alternative configurations:
# 
# For port-forwarding (single node):
# MONGO_URL = "mongodb://admin:password123@localhost:27017/?authSource=admin"
#
# For port-forwarding (full replica set):
# MONGO_URL = "mongodb://admin:password123@localhost:27017,localhost:27018,localhost:27019/?replicaSet=rs0&authSource=admin"
#
# For cluster internal access:
# MONGO_URL = "mongodb://admin:password123@mongo-service.default.svc.cluster.local:27017/?replicaSet=rs0&authSource=admin"

DB_NAME = "result_db"
RAW_COLLECTION_NAME = "raw"
STANDARDIZED_COLLECTION_NAME = "standardized"

# -----------------------------------------------------------------------------
# CORS Configuration
# -----------------------------------------------------------------------------

CORS_ORIGINS = ["*"]  # In production, replace with explicit origins
CORS_CREDENTIALS = True
CORS_METHODS = ["*"]
CORS_HEADERS = ["*"]

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------

LOG_LEVEL = "INFO"
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s' 
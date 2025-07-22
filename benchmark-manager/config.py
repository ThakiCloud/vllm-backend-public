import os

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

# Server Configuration
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8001

# MongoDB Configuration
# Environment-aware configuration:
# - Local development: localhost with port-forward
# - Kubernetes deployment: cluster service names
MONGO_URL = os.getenv(
    "MONGO_URL", 
    "mongodb://admin:password123@mongo-service:27017/?replicaSet=rs0&authSource=admin"
)

DB_NAME = "manage_db"

# Collection Names
PROJECTS_COLLECTION = "projects"
ORIGINAL_FILES_COLLECTION = "original_files"
MODIFIED_FILES_COLLECTION = "modified_files"

# GitHub Configuration
DEFAULT_CONFIG_FOLDER = "config"
DEFAULT_JOB_FOLDER = "job"
GITHUB_API_BASE = "https://api.github.com"

# Polling Configuration
DEFAULT_POLLING_INTERVAL = 86400  # 24 hours in seconds

# File Types
SUPPORTED_CONFIG_EXTENSIONS = ['.yaml', '.yml', '.json']
SUPPORTED_JOB_EXTENSIONS = ['.yaml', '.yml'] 

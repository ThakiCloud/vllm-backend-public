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
def get_default_mongo_url():
    # Check if running in Kubernetes (common indicators)
    if os.getenv("KUBERNETES_SERVICE_HOST") or os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
        # Running in Kubernetes - use cluster service names
        return "mongodb://admin:password@mongo-0.mongo-service:27017,mongo-1.mongo-service:27017,mongo-2.mongo-service:27017/?replicaSet=rs0&authSource=admin"
    else:
        # Local development - use localhost with port-forward
        return "mongodb://admin:password@localhost:27017/?authSource=admin&directConnection=true&serverSelectionTimeoutMS=5000&connectTimeoutMS=5000"

MONGO_URL = os.getenv("MONGO_URL", get_default_mongo_url())
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
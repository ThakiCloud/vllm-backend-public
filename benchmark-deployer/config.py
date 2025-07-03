import os

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

# Server Configuration
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8002

# Kubernetes Configuration
KUBECONFIG_PATH = os.getenv("KUBECONFIG_PATH", "/root/.kube/config")
DEFAULT_NAMESPACE = os.getenv("DEFAULT_NAMESPACE", "default")

# Log Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_TAIL_LINES = int(os.getenv("LOG_TAIL_LINES", "100"))
LOG_FOLLOW_TIMEOUT = int(os.getenv("LOG_FOLLOW_TIMEOUT", "300"))  # 5 minutes

# Deployment Configuration
DEPLOYMENT_TIMEOUT = int(os.getenv("DEPLOYMENT_TIMEOUT", "600"))  # 10 minutes

# -----------------------------------------------------------------------------
# MongoDB Configuration
# -----------------------------------------------------------------------------

# MongoDB Connection URL
MONGO_URL = os.getenv(
    "MONGO_URL", 
    "mongodb://admin:password123@mongo-service:27017/?replicaSet=rs0&authSource=admin"
)

# Database and Collection Names
DB_NAME = "deploy_db"
DEPLOYMENTS_COLLECTION = "deployments" 
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

JOB_MAX_FAILURES = int(os.getenv("JOB_MAX_FAILURES", "3"))  # Maximum failures before termination
JOB_FAILURE_RETRY_DELAY = int(os.getenv("JOB_FAILURE_RETRY_DELAY", "60"))  # Seconds to wait after failure
JOB_TIMEOUT = int(os.getenv("JOB_TIMEOUT", "3600"))  # Default job timeout in seconds

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

# -----------------------------------------------------------------------------
# Service URLs
# -----------------------------------------------------------------------------

# Benchmark Services URLs
BENCHMARK_VLLM_URL = os.getenv(
    "BENCHMARK_VLLM_URL",
    "http://benchmark-vllm:8005"
)

BENCHMARK_MANAGER_URL = os.getenv(
    "BENCHMARK_MANAGER_URL", 
    "http://benchmark-manager:8001"
) 
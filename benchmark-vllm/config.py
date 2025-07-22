import os
from typing import Optional

# Server configuration
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8005"))

# Queue Scheduler configuration
QUEUE_SCHEDULER_AUTO_START = os.getenv("QUEUE_SCHEDULER_AUTO_START", "true").lower() == "true"
QUEUE_SCHEDULER_POLL_INTERVAL = int(os.getenv("QUEUE_SCHEDULER_POLL_INTERVAL", "30"))  # seconds

# Job failure tracking configuration
# 🚨 중요: 이 값들을 너무 높게 설정하면 실패한 작업이 오랫동안 리소스를 점유할 수 있습니다
JOB_MAX_FAILURES = int(os.getenv("JOB_MAX_FAILURES", "3"))  # 최대 실패 횟수 (권장: 2-5)
JOB_FAILURE_RETRY_DELAY = int(os.getenv("JOB_FAILURE_RETRY_DELAY", "60"))  # 실패 후 재시도 대기 시간(초)
JOB_TIMEOUT = int(os.getenv("JOB_TIMEOUT", "3600"))  # Job 최대 실행 시간(초) - 기본 1시간

# VLLM failure tracking configuration  
# 🚨 중요: VLLM 배포 실패는 전체 큐 요청 실패로 이어지므로 신중하게 설정하세요
VLLM_MAX_FAILURES = int(os.getenv("VLLM_MAX_FAILURES", "3"))  # 최대 실패 횟수 (권장: 2-3)
VLLM_FAILURE_RETRY_DELAY = int(os.getenv("VLLM_FAILURE_RETRY_DELAY", "30"))  # 실패 후 재시도 대기 시간(초)
VLLM_TIMEOUT = int(os.getenv("VLLM_TIMEOUT", "600"))  # VLLM 배포 최대 대기 시간(초) - 기본 10분

# Service URLs
DEPLOYER_SERVICE_URL = os.getenv("DEPLOYER_SERVICE_URL", "http://localhost:8002")

# MongoDB configuration
# Environment-aware configuration:
# - Local development: localhost with port-forward
# - Kubernetes deployment: cluster service names
def get_default_mongo_url():
    # Check if running in Kubernetes (common indicators)
    if os.getenv("KUBERNETES_SERVICE_HOST") or os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
        # Running in Kubernetes - use cluster service names
        return "mongodb://admin:password123@mongo-0.mongo-service:27017,mongo-1.mongo-service:27017,mongo-2.mongo-service:27017/?replicaSet=rs0&authSource=admin"
    else:
        # Local development - use localhost with port-forward
        return "mongodb://admin:password123@localhost:27017/?authSource=admin&directConnection=true&serverSelectionTimeoutMS=5000&connectTimeoutMS=5000"

MONGO_URL = os.getenv("MONGO_URL", get_default_mongo_url())
DATABASE_NAME = os.getenv("DATABASE_NAME", "benchmark_vllm")

# vLLM configuration
VLLM_CONFIG_DIR = os.getenv("VLLM_CONFIG_DIR", "./configs")
DEFAULT_CONFIG_FILE = os.getenv("DEFAULT_CONFIG_FILE", "vllm_config.yaml")

# Kubernetes configuration
KUBECONFIG = os.getenv("KUBECONFIG")
VLLM_NAMESPACE = os.getenv("VLLM_NAMESPACE", "vllm")
KUBERNETES_SERVICE_ACCOUNT = os.getenv("KUBERNETES_SERVICE_ACCOUNT", "default")
NAMESPACE = os.getenv("NAMESPACE", "default")
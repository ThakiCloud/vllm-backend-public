import os
try:
    from dotenv import load_dotenv
    # Load environment variables from .env file
    load_dotenv()
except ImportError:
    # dotenv 모듈이 없어도 환경변수는 사용 가능
    pass

# -----------------------------------------------------------------------------
# Application Configuration
# -----------------------------------------------------------------------------

NEW_MODEL_EVALUATION = os.getenv('NEW_MODEL_EVALUATION', 'true')
ARGO_FILE_PATH = os.getenv('ARGO_FILE_PATH', 'argo-application.yaml')

# MLflow Configuration
MLFLOW_TRACKING_URI = os.getenv('MLFLOW_TRACKING_URI')
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '60'))

# Server Configuration
SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.getenv('SERVER_PORT', '8003'))

# GitHub Configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO_OWNER = os.getenv('GITHUB_REPO_OWNER')
GITHUB_REPO_NAME = os.getenv('GITHUB_REPO_NAME')

# Benchmark Eval Configuration
BENCHMARK_EVAL_URL = os.getenv('BENCHMARK_EVAL_URL', 'http://benchmark-eval:8004/evaluate')

# State Management (GitHub 기반으로 전환)



# Default Polling Settings
DEFAULT_POLL_HOURS = 24

def get_github_config():
    """Get GitHub configuration if available."""
    if not GITHUB_TOKEN:
        return None
    
    return {
        'token': GITHUB_TOKEN,
        'repo_owner': GITHUB_REPO_OWNER,
        'repo_name': GITHUB_REPO_NAME,
    }

 
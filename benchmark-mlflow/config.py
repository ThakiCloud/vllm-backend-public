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

NEW_MODEL_EVALUATION = int(os.getenv('NEW_MODEL_EVALUATION', '1'))
YAML_TEMPLATE_PATH = os.getenv('YAML_TEMPLATE_PATH', 'template.yaml')
YAML_MODEL_FILE_PATH = os.getenv('YAML_MODEL_FILE_PATH', '')
ARGO_FILE_PATH = os.getenv('ARGO_FILE_PATH', 'argo-application.yaml')
ARGO_PROJECT_TEMPLATE_PATH = os.getenv('ARGO_PROJECT_TEMPLATE_PATH', 'argo-project-template.yaml')
ARGO_APPLICATION_PATH = os.getenv('ARGO_APPLICATION_PATH', 'applications')
ARGO_PROJECT_PATH = os.getenv('ARGO_PROJECT_PATH', 'projects')

# MLflow Configuration
MLFLOW_TRACKING_URI = os.getenv('MLFLOW_TRACKING_URI', "")
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', '60'))

# Server Configuration
SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.getenv('SERVER_PORT', '8003'))

# GitHub Configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', "")
GITHUB_REPO_OWNER = os.getenv('GITHUB_REPO_OWNER', "")
GITHUB_REPO_NAME = os.getenv('GITHUB_REPO_NAME', "")

# Template Repository Configuration (템플릿용 별도 레포)
TEMPLATE_REPO_OWNER = os.getenv('TEMPLATE_REPO_OWNER', GITHUB_REPO_OWNER)  # 기본값은 메인 레포와 동일
TEMPLATE_REPO_NAME = os.getenv('TEMPLATE_REPO_NAME', GITHUB_REPO_NAME)    # 기본값은 메인 레포와 동일

# Argo Repository Configuration (argo-application.yaml용 별도 레포)
ARGO_REPO_OWNER = os.getenv('ARGO_REPO_OWNER', GITHUB_REPO_OWNER)  # 기본값은 메인 레포와 동일
ARGO_REPO_NAME = os.getenv('ARGO_REPO_NAME', GITHUB_REPO_NAME)      # 기본값은 메인 레포와 동일

# ArgoCD Configuration
ARGOCD_PROJECT_NAME = os.getenv('ARGOCD_PROJECT_NAME', "default")
ARGOCD_REPO_URL = os.getenv('ARGOCD_REPO_URL', "")
ARGOCD_NAMESPACE = os.getenv('ARGOCD_NAMESPACE', "default")

# Benchmark Eval Configuration
BENCHMARK_EVAL_URL = os.getenv('BENCHMARK_EVAL_URL', 'http://benchmark-eval:8004/evaluate')

# Argo Auto Deploy Configuration
ARGO_AUTO_DEPLOY = int(os.getenv('ARGO_AUTO_DEPLOY', '1'))

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

 
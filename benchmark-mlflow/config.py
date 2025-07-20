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

# Inference Engine Configuration
INFERENCE_ENGINE_TYPE = os.getenv('INFERENCE_ENGINE_TYPE')  # vllm, tensorrt-llm, all

# 동적 경로 생성
def get_yaml_model_file_path(engine_type: str = None) -> str:
    """INFERENCE_ENGINE_TYPE에 따른 YAML 모델 파일 경로 반환"""
    if engine_type is None:
        engine_type = INFERENCE_ENGINE_TYPE
    
    if engine_type.lower() == "all":
        return ""  # all 타입인 경우 각 엔진별로 별도 처리
    else:
        return engine_type.lower()

def get_yaml_template_path(engine_type: str = None) -> str:
    """INFERENCE_ENGINE_TYPE에 따른 YAML 템플릿 경로 반환"""
    if engine_type is None:
        engine_type = INFERENCE_ENGINE_TYPE
    
    # 환경변수에서 직접 template 베이스 경로 가져오기
    template_base = os.getenv('YAML_TEMPLATE_PATH', 'template')
    
    if engine_type.lower() == "all":
        return template_base  # all 타입인 경우 기본 경로만 반환
    else:
        return f"{template_base}/{engine_type.lower()}.yaml"

# 동적으로 생성되는 경로들 (기본값만 설정, 실제로는 함수 사용)
YAML_MODEL_FILE_PATH = get_yaml_model_file_path()  # 하위 호환성용
YAML_TEMPLATE_PATH = os.getenv('YAML_TEMPLATE_PATH', 'template')  # 기본 템플릿 베이스 경로

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

# Benchmark Eval Configuration
BENCHMARK_EVAL_URL = os.getenv('BENCHMARK_EVAL_URL', 'http://benchmark-eval:8004/evaluate')
ENGINE_NAMESPACE = os.getenv('ENGINE_NAMESPACE', "default")
ENGINE_PORT = os.getenv('ENGINE_PORT', "8000")

# ArgoCD Configuration
ARGOCD_PROJECT_NAME = os.getenv('ARGOCD_PROJECT_NAME', "default")
ARGOCD_REPO_URL = os.getenv('ARGOCD_REPO_URL', "")
ARGOCD_NAMESPACE = os.getenv('ARGOCD_NAMESPACE', ENGINE_NAMESPACE)

# Argo Auto Deploy Configuration
ARGO_AUTO_DEPLOY = int(os.getenv('ARGO_AUTO_DEPLOY', '1'))
EVALUATION_ENABLED = int(os.getenv('EVALUATION_ENABLED', '1'))

# State Management (GitHub 기반으로 전환)



# Default Polling Settings
DEFAULT_POLL_HOURS = 24

def get_engines_to_process() -> list:
    """INFERENCE_ENGINE_TYPE에 따른 처리할 엔진 목록 반환"""
    engine_type = INFERENCE_ENGINE_TYPE.lower() if INFERENCE_ENGINE_TYPE else 'vllm'
    
    if engine_type == "all":
        return ['vllm', 'tensorrt-llm']
    elif engine_type in ['vllm', 'tensorrt-llm']:
        return [engine_type]
    else:
        # 기본값
        return ['vllm']

def get_github_config():
    """Get GitHub configuration if available."""
    if not GITHUB_TOKEN:
        return None
    
    return {
        'token': GITHUB_TOKEN,
        'repo_owner': GITHUB_REPO_OWNER,
        'repo_name': GITHUB_REPO_NAME,
    }

 
import logging
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uvicorn

from config import (
    MLFLOW_TRACKING_URI, 
    POLLING_INTERVAL,
    get_github_config,
    SERVER_HOST,
    SERVER_PORT
)
from models import GitHubConfig, MLflowConfig, HealthResponse, PollResponse, ConnectionStatus
from mlflow_manager import MLflowManager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="MLflow GitHub Integration API",
    description="API for managing MLflow model integration with GitHub",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 글로벌 MLflow Manager 인스턴스
mlflow_manager: Optional[MLflowManager] = None

# -----------------------------------------------------------------------------
# 시작/종료 이벤트
# -----------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    global mlflow_manager
    
    logger.info("MLflow GitHub Integration Service 시작")
    
    try:
        # GitHub 설정 (선택사항)
        github_config = None
        github_config_dict = get_github_config()
        if github_config_dict:
            github_config = GitHubConfig(**github_config_dict)
            logger.info(f"GitHub 설정 로드 완료: {github_config.repo_owner}/{github_config.repo_name}")
        else:
            logger.warning("GitHub 설정이 없습니다. GitHub 연동이 비활성화됩니다.")
        
        # MLflow Manager 초기화
        mlflow_manager = MLflowManager(
            mlflow_tracking_uri=MLFLOW_TRACKING_URI,
            polling_interval=POLLING_INTERVAL,
            github_config=github_config
        )
        
        # 연결 테스트
        logger.info("연결 테스트 시작...")
        test_results = mlflow_manager.test_connections()
        
        for service, result in test_results.items():
            if result is None:
                logger.info(f"{service}: 설정되지 않음")
            elif result:
                logger.info(f"{service}: 연결 성공")
            else:
                logger.error(f"{service}: 연결 실패")
        
        # MLflow 연결이 실패한 경우 경고
        if not test_results.get('mlflow', False):
            logger.error("MLflow 연결 실패. 수동 폴링 시 연결을 재시도합니다.")
        
        # 자동 폴링 시작
        logger.info("자동 폴링 서비스 시작...")
        mlflow_manager.start_polling()
        
    except Exception as e:
        logger.error(f"서비스 초기화 중 오류 발생: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행"""
    global mlflow_manager
    
    if mlflow_manager:
        logger.info("MLflow Manager 종료 중...")
        mlflow_manager.stop_polling()
        logger.info("MLflow Manager 종료 완료")

# -----------------------------------------------------------------------------
# Health Check API
# -----------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    global mlflow_manager
    
    if not mlflow_manager:
        return HealthResponse(
            status="unhealthy",
            service="benchmark-mlflow",
            timestamp=datetime.now(),
            mlflow_connected=False,
            github_connected=False
        )
    
    # 연결 상태 확인
    test_results = mlflow_manager.test_connections()
    
    return HealthResponse(
        status="healthy" if test_results.get('mlflow', False) else "degraded",
        service="benchmark-mlflow",
        timestamp=datetime.now(),
        mlflow_connected=test_results.get('mlflow', False),
        github_connected=test_results.get('github')
    )

# -----------------------------------------------------------------------------
# 폴링 API
# -----------------------------------------------------------------------------

@app.post("/poll", response_model=PollResponse)
async def manual_poll():
    """수동 폴링 API - 즉시 MLflow에서 새 모델 버전을 확인"""
    global mlflow_manager
    
    if not mlflow_manager:
        raise HTTPException(status_code=503, detail="MLflow Manager가 초기화되지 않았습니다.")
    
    try:
        logger.info("수동 폴링 시작...")
        
        # 연결 테스트
        test_results = mlflow_manager.test_connections()
        if not test_results.get('mlflow', False):
            raise HTTPException(status_code=502, detail="MLflow 서버에 연결할 수 없습니다.")
        
        # 수동 폴링 실행
        result = mlflow_manager.poll_once()
        
        return PollResponse(
            status="success" if result.success else "warning",
            timestamp=datetime.now(),
            message="수동 폴링 완료",
            processed_models=result.events_count,
            new_models=result.github_updates,
            errors=result.errors
        )
        
    except Exception as e:
        logger.error(f"수동 폴링 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/connections", response_model=ConnectionStatus)
async def get_connections():
    """연결 상태 확인 API"""
    global mlflow_manager
    
    if not mlflow_manager:
        return ConnectionStatus(
            mlflow_connected=False,
            github_connected=False,
            mlflow_uri=MLFLOW_TRACKING_URI,
            github_repo=None,
            last_check=datetime.now()
        )
    
    test_results = mlflow_manager.test_connections()
    github_config = mlflow_manager.github_config
    
    return ConnectionStatus(
        mlflow_connected=test_results.get('mlflow', False),
        github_connected=test_results.get('github'),
        mlflow_uri=MLFLOW_TRACKING_URI,
        github_repo=f"{github_config.repo_owner}/{github_config.repo_name}" if github_config else None,
        last_check=datetime.now()
    )

# -----------------------------------------------------------------------------
# 메인 함수
# -----------------------------------------------------------------------------

def main():
    """메인 함수 - uvicorn으로 FastAPI 서버 실행"""
    logger.info("Starting MLflow GitHub Integration API Server")
    
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="info"
    )

if __name__ == "__main__":
    main()
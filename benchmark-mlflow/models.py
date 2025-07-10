from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import time

# -----------------------------------------------------------------------------
# Event Models
# -----------------------------------------------------------------------------

class ModelEvent(BaseModel):
    """MLflow 모델 이벤트 데이터 모델"""
    event_type: str = Field(..., description="이벤트 타입 (model_registered, model_version_created)")
    model_name: str = Field(..., description="모델 이름")
    version: Optional[str] = Field(None, description="모델 버전")
    run_id: Optional[str] = Field(None, description="MLflow 실행 ID")
    status: Optional[str] = Field(None, description="모델 상태")
    user_id: Optional[str] = Field(None, description="사용자 ID")
    creation_time: Optional[int] = Field(None, description="생성 시간 (밀리초)")
    source: Optional[str] = Field(None, description="소스 경로")
    description: Optional[str] = Field(None, description="설명")
    timestamp: Optional[float] = Field(default_factory=time.time, description="이벤트 타임스탬프")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# -----------------------------------------------------------------------------
# GitHub Models
# -----------------------------------------------------------------------------

class GitHubFileUpdate(BaseModel):
    """GitHub 파일 업데이트 정보"""
    file_path: str = Field(..., description="파일 경로")
    content: str = Field(..., description="파일 내용")
    commit_message: str = Field(..., description="커밋 메시지")
    branch: str = Field("main", description="브랜치명")
    sha: Optional[str] = Field(None, description="파일 SHA")

class GitHubConfig(BaseModel):
    """GitHub 설정 정보"""
    token: str = Field(..., description="GitHub 토큰")
    repo_owner: str = Field(..., description="저장소 소유자")
    repo_name: str = Field(..., description="저장소 이름")

# -----------------------------------------------------------------------------
# Database Models
# -----------------------------------------------------------------------------



# -----------------------------------------------------------------------------
# Service Models
# -----------------------------------------------------------------------------

# PollingState 클래스 제거 - GitHub 기반 상태 관리로 전환

class PollingResult(BaseModel):
    """폴링 결과 정보"""
    events_count: int = Field(..., description="감지된 이벤트 수")
    github_updates: int = Field(..., description="GitHub 업데이트 수")
    success: bool = Field(..., description="전체 성공 여부")
    errors: List[str] = Field(default_factory=list, description="오류 목록")
    timestamp: datetime = Field(default_factory=datetime.now, description="폴링 시간")

# -----------------------------------------------------------------------------
# Configuration Models
# -----------------------------------------------------------------------------

class MLflowConfig(BaseModel):
    """MLflow 설정 정보"""
    tracking_uri: str = Field(..., description="MLflow 추적 URI")
    polling_interval: int = Field(60, description="폴링 간격(초)")

class ServiceConfig(BaseModel):
    """서비스 전체 설정"""
    mlflow: MLflowConfig = Field(..., description="MLflow 설정")
    github: Optional[GitHubConfig] = Field(None, description="GitHub 설정")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# -----------------------------------------------------------------------------
# FastAPI Response Models
# -----------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Health check 응답 모델"""
    status: str = Field(..., description="서비스 상태")
    service: str = Field(..., description="서비스 이름")
    timestamp: datetime = Field(..., description="응답 시간")
    mlflow_connected: bool = Field(..., description="MLflow 연결 상태")
    github_connected: Optional[bool] = Field(None, description="GitHub 연결 상태")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class PollResponse(BaseModel):
    """수동 폴링 응답 모델"""
    status: str = Field(..., description="폴링 상태")
    timestamp: datetime = Field(..., description="폴링 시간")
    message: str = Field(..., description="폴링 메시지")
    processed_models: int = Field(..., description="처리된 모델 수")
    new_models: int = Field(..., description="새로 발견된 모델 수")
    errors: List[str] = Field(default_factory=list, description="오류 목록")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class ConnectionStatus(BaseModel):
    """연결 상태 응답 모델"""
    mlflow_connected: bool = Field(..., description="MLflow 연결 상태")
    github_connected: Optional[bool] = Field(None, description="GitHub 연결 상태")
    mlflow_uri: str = Field(..., description="MLflow URI")
    github_repo: Optional[str] = Field(None, description="GitHub 저장소")
    last_check: datetime = Field(..., description="마지막 확인 시간")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        } 
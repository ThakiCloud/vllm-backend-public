from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import uuid4

# -----------------------------------------------------------------------------
# Project Models
# -----------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(..., description="Project name")
    project_type: Optional[str] = Field("benchmark", description="Project type: benchmark or vllm")
    repository_url: str = Field(..., description="GitHub repository URL (e.g., https://api.github.com/repos/owner/repo)")
    github_token: str = Field(..., description="GitHub personal access token")
    config_path: Optional[str] = Field("config", description="Config folder path in repository")
    job_path: Optional[str] = Field("job", description="Job folder path in repository")
    vllm_values_path: Optional[str] = Field("", description="VLLM values files path in repository")
    polling_interval: Optional[int] = Field(86400, description="Polling interval in seconds")

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    project_type: Optional[str] = None
    repository_url: Optional[str] = None
    github_token: Optional[str] = None
    config_path: Optional[str] = None
    job_path: Optional[str] = None
    vllm_values_path: Optional[str] = None
    polling_interval: Optional[int] = None

class Project(BaseModel):
    project_id: str
    name: str
    project_type: Optional[str] = "benchmark"
    repository_url: str
    github_token: str
    config_path: str
    job_path: str
    vllm_values_path: Optional[str] = ""
    polling_interval: int
    created_at: datetime
    updated_at: datetime
    last_sync: Optional[datetime] = None

# -----------------------------------------------------------------------------
# File Models
# -----------------------------------------------------------------------------

class OriginalFile(BaseModel):
    file_id: str
    project_id: str
    file_path: str
    file_type: str
    content: str
    sha: str
    last_modified: datetime
    synced_at: datetime

class ModifiedFile(BaseModel):
    file_id: Optional[str] = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    modified: bool = True
    file_type: str
    file_path: str
    content: str
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None

# -----------------------------------------------------------------------------
# API Request/Response Models
# -----------------------------------------------------------------------------

class SyncRequest(BaseModel):
    project_id: str

class SyncResponse(BaseModel):
    status: str
    message: str
    synced_files: int
    project_id: str

class FileListResponse(BaseModel):
    original_files: List[OriginalFile]
    modified_files: List[ModifiedFile]

class ProjectStats(BaseModel):
    total_original_files: int
    total_modified_files: int
    config_files: int
    job_files: int
    last_sync: Optional[datetime]

class ProjectWithStats(BaseModel):
    project: Project
    stats: ProjectStats

# -----------------------------------------------------------------------------
# System Models
# -----------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: datetime

class SystemStatus(BaseModel):
    service: str
    status: str
    total_projects: int
    total_files: int
    uptime: str 
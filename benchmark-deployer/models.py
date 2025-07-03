from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class DeploymentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"

class ResourceType(str, Enum):
    JOB = "job"
    DEPLOYMENT = "deployment"
    SERVICE = "service"
    CONFIGMAP = "configmap"
    SECRET = "secret"
    UNKNOWN = "unknown"

# -----------------------------------------------------------------------------
# Request Models
# -----------------------------------------------------------------------------

class DeploymentRequest(BaseModel):
    yaml_content: str = Field(..., description="YAML content as string")
    namespace: Optional[str] = Field("default", description="Kubernetes namespace")
    name: Optional[str] = Field(None, description="Optional deployment name")

class LogRequest(BaseModel):
    job_name: str = Field(..., description="Job name to get logs from")
    namespace: Optional[str] = Field("default", description="Kubernetes namespace")
    tail_lines: Optional[int] = Field(100, description="Number of lines to tail")
    follow: Optional[bool] = Field(False, description="Whether to follow logs")

class DeleteRequest(BaseModel):
    yaml_content: str = Field(..., description="YAML content as string (same as used for deployment)")
    namespace: Optional[str] = Field("default", description="Kubernetes namespace")

# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------

class DeploymentResponse(BaseModel):
    status: str
    message: str
    deployment_id: str
    namespace: str
    resource_type: ResourceType
    resource_name: str
    yaml_content: str
    created_at: datetime

class LogResponse(BaseModel):
    job_name: str
    namespace: str
    logs: List[str]
    timestamp: datetime

class DeleteResponse(BaseModel):
    status: str
    message: str
    deleted_resources: List[Dict[str, str]]
    namespace: str
    timestamp: datetime

class JobStatusResponse(BaseModel):
    job_name: str
    namespace: str
    status: DeploymentStatus
    phase: Optional[str] = None
    start_time: Optional[datetime] = None
    completion_time: Optional[datetime] = None
    active_pods: int = 0
    succeeded_pods: int = 0
    failed_pods: int = 0

# -----------------------------------------------------------------------------
# System Models
# -----------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: datetime
    kubernetes_connected: bool

class SystemStatus(BaseModel):
    service: str
    status: str
    kubernetes_version: Optional[str] = None
    active_deployments: int = 0
    uptime: str

# -----------------------------------------------------------------------------
# Terminal Session Models
# -----------------------------------------------------------------------------

class TerminalSessionRequest(BaseModel):
    job_name: str = Field(..., description="Job name to access terminal")
    namespace: Optional[str] = Field("default", description="Kubernetes namespace")
    pod_name: Optional[str] = Field(None, description="Specific pod name (optional)")
    container_name: Optional[str] = Field(None, description="Container name (optional)")
    shell: Optional[str] = Field("/bin/bash", description="Shell to use")

class TerminalSessionResponse(BaseModel):
    session_id: str
    job_name: str
    namespace: str
    pod_name: Optional[str] = None
    container_name: Optional[str] = None
    shell: str
    websocket_url: str
    created_at: datetime

class TerminalSessionInfo(BaseModel):
    session_id: str
    job_name: str
    namespace: str
    pod_name: Optional[str] = None
    container_name: Optional[str] = None
    shell: str
    is_active: bool
    created_at: datetime
    last_activity: datetime

class TerminalSessionListResponse(BaseModel):
    sessions: List[TerminalSessionInfo]
    total_sessions: int
    active_sessions: int 
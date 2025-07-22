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

# VLLM Helm Deployment Models
class VLLMHelmConfig(BaseModel):
    project_id: Optional[str] = Field(None, description="VLLM project ID")
    values_file_id: Optional[str] = Field(None, description="Custom values file ID")
    release_name: str = Field("vllm-deployment", description="Helm release name")
    namespace: str = Field("vllm", description="Kubernetes namespace")
    chart_path: str = Field("./charts/vllm", description="Path to Helm chart")
    additional_args: Optional[str] = Field(None, description="Additional Helm arguments")

class VLLMHelmDeploymentRequest(BaseModel):
    vllm_config: Optional[Dict[str, Any]] = Field(None, description="VLLM configuration (optional when skip_vllm_creation is True)")
    vllm_helm_config: VLLMHelmConfig = Field(..., description="VLLM Helm configuration")
    benchmark_configs: Optional[List[Dict[str, Any]]] = Field([], description="Benchmark job configurations")
    scheduling_config: Optional[Dict[str, Any]] = Field(None, description="Scheduling configuration")
    priority: str = Field("medium", description="Deployment priority")
    vllm_yaml_content: Optional[str] = Field(None, description="Raw VLLM YAML content")
    skip_vllm_creation: bool = Field(False, description="Skip VLLM creation and use existing VLLM")

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

# -----------------------------------------------------------------------------
# VLLM Models (Integrated from benchmark-vllm)
# -----------------------------------------------------------------------------

class VLLMConfig(BaseModel):
    """vLLM configuration model"""
    model_name: str = Field(..., description="Model name to deploy")
    gpu_memory_utilization: float = Field(0.0, description="GPU memory utilization ratio")
    max_num_seqs: int = Field(2, description="Maximum number of sequences")
    block_size: int = Field(16, description="Block size for memory allocation")
    tensor_parallel_size: int = Field(1, description="Tensor parallel size")
    pipeline_parallel_size: int = Field(1, description="Pipeline parallel size")
    trust_remote_code: bool = Field(False, description="Trust remote code")
    dtype: str = Field("float32", description="Data type")
    max_model_len: Optional[int] = Field(512, description="Maximum model length")
    quantization: Optional[str] = Field(None, description="Quantization method")
    served_model_name: Optional[str] = Field("test-model-cpu", description="Served model name")
    port: int = Field(8000, description="Server port")
    host: str = Field("0.0.0.0", description="Server host")
    namespace: str = Field("vllm", description="Kubernetes namespace")
    # GPU resource configuration
    gpu_resource_type: str = Field("cpu", description="GPU resource type")
    gpu_resource_count: int = Field(0, description="Number of GPU resources to request")
    additional_args: Optional[Dict[str, Any]] = Field(default_factory=lambda: {
        "disable-log-stats": True,
        "disable-log-requests": True,
        "enforce-eager": True,
        "disable-custom-all-reduce": True
    }, description="Additional vLLM arguments")

    def get_resource_key(self) -> str:
        """Get a unique key for GPU resource identification"""
        return f"{self.gpu_resource_type}:{self.gpu_resource_count}"

    def matches_config(self, other: 'VLLMConfig') -> bool:
        """Check if this config matches another config for deployment reuse"""
        # Core model and deployment settings that affect compatibility
        core_fields = [
            'model_name', 'gpu_memory_utilization', 'max_num_seqs', 'block_size',
            'tensor_parallel_size', 'pipeline_parallel_size', 'trust_remote_code',
            'dtype', 'max_model_len', 'quantization', 'served_model_name',
            'gpu_resource_type', 'gpu_resource_count'
        ]
        
        for field in core_fields:
            if getattr(self, field) != getattr(other, field):
                return False
        
        # Check additional args
        if self.additional_args != other.additional_args:
            return False
            
        return True

    def conflicts_with_gpu_resources(self, other: 'VLLMConfig') -> bool:
        """Check if this config conflicts with another config's GPU resources"""
        # Same GPU resource type indicates potential conflict
        if self.gpu_resource_type == other.gpu_resource_type:
            return True
        
        # Check for MIG resource conflicts (same MIG slice type)
        if (self.gpu_resource_type.startswith("nvidia.com/mig-") and 
            other.gpu_resource_type.startswith("nvidia.com/mig-")):
            # Extract MIG slice info (e.g., "3g.20gb" from "nvidia.com/mig-3g.20gb")
            self_mig_slice = self.gpu_resource_type.split("nvidia.com/mig-")[-1]
            other_mig_slice = other.gpu_resource_type.split("nvidia.com/mig-")[-1]
            if self_mig_slice == other_mig_slice:
                return True
        
        return False

class BenchmarkJobConfig(BaseModel):
    """Configuration for a single benchmark job"""
    yaml_content: str = Field(..., description="Kubernetes Job YAML content")
    namespace: str = Field("default", description="Kubernetes namespace")
    project_id: Optional[str] = Field(None, description="Project ID for file selection")
    job_file_id: Optional[str] = Field(None, description="Job file ID")
    config_file_id: Optional[str] = Field(None, description="Config file ID")
    name: Optional[str] = Field(None, description="Benchmark job name")

class SchedulingConfig(BaseModel):
    """Scheduling configuration for queue requests"""
    immediate: bool = Field(True, description="Deploy immediately")
    scheduled_time: Optional[datetime] = Field(None, description="Scheduled deployment time")
    max_wait_time: int = Field(3600, description="Maximum wait time in seconds")

class VLLMDeploymentQueueRequest(BaseModel):
    """Request model for adding VLLM deployment + benchmark jobs to queue"""
    vllm_config: Optional[VLLMConfig] = Field(None, description="VLLM configuration (optional when skip_vllm_creation is True)")
    benchmark_configs: List[BenchmarkJobConfig] = Field(default_factory=list, description="List of benchmark jobs")
    scheduling_config: Optional[SchedulingConfig] = Field(default_factory=SchedulingConfig, description="Scheduling configuration")
    priority: str = Field("medium", description="Priority level: low, medium, high, urgent")
    skip_vllm_creation: bool = Field(False, description="Skip VLLM creation and use existing VLLM")

class VLLMDeploymentQueueResponse(BaseModel):
    """Response model for VLLM deployment queue operations"""
    queue_request_id: str
    priority: str
    status: str  # pending, processing, completed, failed, cancelled
    vllm_config: Optional[VLLMConfig] = Field(None, description="VLLM configuration (None when skip_vllm_creation is True)")
    benchmark_configs: List[BenchmarkJobConfig]
    scheduling_config: SchedulingConfig
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    vllm_deployment_id: Optional[str] = None
    benchmark_job_ids: List[str] = Field(default_factory=list)
    current_step: str = Field("pending", description="Current processing step")
    total_steps: int = Field(1, description="Total number of steps")
    completed_steps: int = Field(0, description="Number of completed steps")
    error_message: Optional[str] = None

class VLLMQueueStatusResponse(BaseModel):
    """Response model for VLLM queue status overview"""
    total_requests: int
    pending_requests: int
    processing_requests: int
    completed_requests: int
    failed_requests: int
    cancelled_requests: int

class VLLMDeploymentResponse(BaseModel):
    """Response model for VLLM deployment"""
    deployment_id: str
    deployment_name: str
    status: str
    config: VLLMConfig
    created_at: datetime
    message: str

# Priority change request
class QueuePriorityRequest(BaseModel):
    """Request model for changing queue priority"""
    priority: str = Field(..., description="New priority level") 
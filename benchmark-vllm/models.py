from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime

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
    # GPU resource configuration
    gpu_resource_type: str = Field("cpu", description="GPU resource type (e.g., nvidia.com/gpu, nvidia.com/mig-3g.20gb)")
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

class VLLMDeployment(BaseModel):
    """vLLM deployment record for Helm-based deployments"""
    deployment_id: str
    config: VLLMConfig
    status: str  # deploying, running, failed, stopped
    helm_release_name: Optional[str] = None
    namespace: str = "vllm"
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None

class VLLMDeploymentRequest(BaseModel):
    """Request model for vLLM deployment"""
    config: VLLMConfig
    deployment_name: Optional[str] = Field(None, description="Deployment name")
    github_token: Optional[str] = Field(None, description="GitHub token for accessing private repositories")

class VLLMDeploymentResponse(BaseModel):
    """Response model for vLLM deployment"""
    deployment_id: str
    deployment_name: str
    status: str
    config: VLLMConfig
    created_at: datetime
    message: str

class VLLMStatusResponse(BaseModel):
    """Response model for vLLM status"""
    deployment_id: str
    deployment_name: str
    status: str
    uptime: Optional[str] = None
    error_message: Optional[str] = None

class ConfigFileRequest(BaseModel):
    """Request model for loading config from file"""
    config_file: str = Field(..., description="Path to configuration file")

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: datetime
    service: str = "benchmark-vllm"

class SystemStatus(BaseModel):
    """System status information"""
    service: str
    status: str
    uptime: str
    active_deployments: int
    last_check: datetime

# Queue related models
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

class QueueRequest(BaseModel):
    """Request model for adding to deployment queue"""
    vllm_config: Optional[VLLMConfig] = Field(None, description="VLLM configuration (optional when skip_vllm_creation is True)")
    benchmark_configs: List[BenchmarkJobConfig] = Field(default_factory=list, description="List of benchmark jobs")
    scheduling_config: Optional[SchedulingConfig] = Field(default_factory=SchedulingConfig, description="Scheduling configuration")
    priority: str = Field("medium", description="Priority level: low, medium, high, urgent")
    vllm_yaml_content: Optional[str] = Field(None, description="Raw VLLM YAML content for legacy deployments")
    # Helm deployment fields
    helm_deployment: bool = Field(False, description="Whether this is a Helm deployment")
    helm_config: Optional[Dict[str, Any]] = Field(None, description="Helm configuration for Helm deployments")
    skip_vllm_creation: bool = Field(False, description="Skip VLLM creation and use existing VLLM")
    # GitHub integration
    github_token: Optional[str] = Field(None, description="GitHub token for accessing private repositories (from project)")
    repository_url: Optional[str] = Field(None, description="GitHub repository URL for charts cloning")

class QueueResponse(BaseModel):
    """Response model for queue operations"""
    queue_request_id: str
    priority: str
    status: str
    vllm_config: Optional[VLLMConfig] = Field(None, description="VLLM configuration (None when skip_vllm_creation is True)")
    benchmark_configs: List[BenchmarkJobConfig]
    scheduling_config: SchedulingConfig
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    deployment_id: Optional[str] = None
    error_message: Optional[str] = None
    # Helm deployment fields
    helm_deployment: bool = Field(False, description="Whether this is a Helm deployment")
    helm_config: Optional[Dict[str, Any]] = Field(None, description="Helm configuration for Helm deployments")

class QueueStatusResponse(BaseModel):
    """Response model for queue status overview"""
    total_requests: int
    pending_requests: int
    processing_requests: int
    completed_requests: int
    failed_requests: int
    cancelled_requests: int

class QueuePriorityRequest(BaseModel):
    """Request model for changing queue priority"""
    priority: str = Field(..., description="New priority level")
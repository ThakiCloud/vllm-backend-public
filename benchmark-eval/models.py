from pydantic import BaseModel, Field, validator
from typing import Dict, Any, Optional


class ModelRequest(BaseModel):
    """Request model for evaluation deployment"""
    model_name: str = Field(..., description="Name of the model to evaluate")
    inference_engine_url: str = Field(..., description="URL of the inference engine service", alias="inference-engine-url")
    
    model_config = {
        "populate_by_name": True,  # This allows both field names and aliases
    }
    
    @validator('model_name')
    def validate_model_name(cls, v):
        if not v or not v.strip():
            raise ValueError('model_name cannot be empty')
        return v.strip()
    
    @validator('inference_engine_url')
    def validate_inference_engine_url(cls, v):
        if not v or not v.strip():
            raise ValueError('inference_engine_url cannot be empty')
        if not v.startswith(('http://', 'https://')):
            raise ValueError('inference_engine_url must be a valid URL')
        return v.strip()


class DeploymentRequest(BaseModel):
    """Request model for deployment to benchmark-deploy service"""
    yaml_content: str = Field(..., description="YAML content for deployment")
    namespace: str = Field(default="default", description="Kubernetes namespace")
    name: str = Field(..., description="Name of the deployment")


class EvaluationResponse(BaseModel):
    """Response model for evaluation requests"""
    message: str = Field(..., description="Success message")
    model_name: str = Field(..., description="Name of the model")
    inference_engine_url: str = Field(..., description="URL of the inference engine service")
    deployment_response: Optional[Dict[str, Any]] = Field(None, description="Response from deployment service")


class HealthResponse(BaseModel):
    """Response model for health check"""
    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")


class ErrorResponse(BaseModel):
    """Error response model"""
    detail: str = Field(..., description="Error details") 
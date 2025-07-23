from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging
from datetime import datetime
from typing import List, Dict, Any

# Import our modules
from config import SERVER_HOST, SERVER_PORT, VLLM_CONFIG_DIR, DEFAULT_CONFIG_FILE
from database import connect_to_mongo, close_mongo_connection
from models import (
    VLLMConfig, VLLMDeploymentRequest, VLLMDeploymentResponse,
    VLLMStatusResponse, ConfigFileRequest, HealthResponse, SystemStatus,
    QueueRequest, QueueResponse, QueueStatusResponse, QueuePriorityRequest
)
from vllm_manager import vllm_manager
from queue_manager import queue_manager
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------

app = FastAPI(
    title="Benchmark vLLM API",
    description="API for deploying and managing vLLM servers with configurable parameters",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Startup/Shutdown Events
# -----------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    """Initialize application."""
    logger.info("Starting Benchmark vLLM API...")
    await connect_to_mongo()
    
    # Initialize vLLM manager
    await vllm_manager.initialize()
    
    # Initialize queue manager with auto-start scheduler
    await queue_manager.initialize()
    
    # Create config directory if it doesn't exist
    os.makedirs(VLLM_CONFIG_DIR, exist_ok=True)
    logger.info(f"Config directory: {VLLM_CONFIG_DIR}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Benchmark vLLM API...")
    
    # Shutdown queue manager (stops scheduler)
    await queue_manager.shutdown()
    
    # Don't stop running deployments - let them continue running
    # This allows vLLM instances to persist even if the management service is restarted
    logger.info("Leaving vLLM deployments running for independent operation")
    
    await close_mongo_connection()

# -----------------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow()
    )

@app.get("/status", response_model=SystemStatus)
async def system_status():
    """Get system status."""
    deployments = await vllm_manager.list_deployments()
    
    # Count active deployments, handling both VLLMDeployment objects and dicts
    active_count = 0
    for d in deployments.values():
        if hasattr(d, 'status'):
            # It's a VLLMDeployment object
            if d.status == "running":
                active_count += 1
        elif isinstance(d, dict) and d.get("status") == "running":
            # It's a dict
            active_count += 1
    
    return SystemStatus(
        service="benchmark-vllm",
        status="healthy",
        uptime="N/A",  # TODO: Calculate actual uptime
        active_deployments=active_count,
        last_check=datetime.utcnow()
    )

# -----------------------------------------------------------------------------
# vLLM Deployment Endpoints
# -----------------------------------------------------------------------------

@app.post("/deploy", response_model=VLLMDeploymentResponse)
async def deploy_vllm(request: VLLMDeploymentRequest):
    """Deploy vLLM server with given configuration."""
    try:
        # Generate deployment ID if not provided
        deployment_id = request.deployment_name or f"vllm-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        response = await vllm_manager.deploy_vllm_with_helm(
            config=request.config,
            deployment_id=deployment_id,
            github_token=request.github_token
        )
        return response
    except Exception as e:
        logger.error(f"Failed to deploy vLLM: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deploy-from-file", response_model=VLLMDeploymentResponse)
async def deploy_vllm_from_file(request: ConfigFileRequest):
    """Deploy vLLM server from YAML configuration file."""
    try:
        config_path = os.path.join(VLLM_CONFIG_DIR, request.config_file)
        config = await vllm_manager.load_config_from_yaml(config_path)
        
        response = await vllm_manager.deploy_vllm(config=config)
        return response
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Configuration file not found: {request.config_file}")
    except Exception as e:
        logger.error(f"Failed to deploy vLLM from file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/deploy-default", response_model=VLLMDeploymentResponse)
async def deploy_vllm_default():
    """Deploy vLLM server using default configuration file."""
    try:
        config_path = os.path.join(VLLM_CONFIG_DIR, DEFAULT_CONFIG_FILE)
        config = await vllm_manager.load_config_from_yaml(config_path)
        
        response = await vllm_manager.deploy_vllm(config=config)
        return response
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Default configuration file not found: {DEFAULT_CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Failed to deploy vLLM with default config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/deployments/{deployment_id}/status", response_model=VLLMStatusResponse)
async def get_deployment_status(deployment_id: str):
    """Get status of a specific deployment."""
    deployment_info = await vllm_manager.get_deployment_status(deployment_id)
    
    if not deployment_info:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    # Handle both VLLMDeployment object and dict formats
    if hasattr(deployment_info, 'dict'):
        # It's a VLLMDeployment object
        return VLLMStatusResponse(
            deployment_id=deployment_id,
            deployment_name=deployment_info.helm_release_name or deployment_id,  # Use helm_release_name as deployment_name
            status=deployment_info.status,
            error_message=deployment_info.error_message
        )
    else:
        # It's already a dict (legacy format)
        return VLLMStatusResponse(
            deployment_id=deployment_id,
            deployment_name=deployment_info.get("deployment_name", deployment_info.get("helm_release_name", deployment_id)),
            status=deployment_info["status"],
            error_message=deployment_info.get("error_message")
        )

@app.get("/deployments", response_model=Dict[str, Dict[str, Any]])
async def list_deployments():
    """List all deployments."""
    deployments = await vllm_manager.list_deployments()
    
    # Convert VLLMDeployment objects to dictionaries
    result = {}
    for deployment_id, deployment in deployments.items():
        if hasattr(deployment, 'dict'):
            # It's a Pydantic model, convert to dict
            deployment_dict = deployment.dict()
            # Ensure config is also converted to dict
            if 'config' in deployment_dict and hasattr(deployment_dict['config'], 'dict'):
                deployment_dict['config'] = deployment_dict['config'].dict()
            result[deployment_id] = deployment_dict
        else:
            # It's already a dict
            result[deployment_id] = deployment
    
    return result

@app.delete("/deployments/{deployment_id}")
async def stop_deployment(deployment_id: str):
    """Stop a specific deployment."""
    success = await vllm_manager.stop_deployment(deployment_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Deployment not found or failed to stop")
    
    return {"message": f"Deployment {deployment_id} stopped successfully"}

# -----------------------------------------------------------------------------
# Configuration Endpoints
# -----------------------------------------------------------------------------

@app.get("/configs/validate")
async def validate_config(config: VLLMConfig):
    """Validate vLLM configuration."""
    try:
        # Basic validation is handled by Pydantic
        # Additional custom validation can be added here
        return {"valid": True, "message": "Configuration is valid"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {e}")

@app.get("/configs/files")
async def list_config_files():
    """List available configuration files."""
    try:
        if not os.path.exists(VLLM_CONFIG_DIR):
            return {"files": []}
        
        files = [f for f in os.listdir(VLLM_CONFIG_DIR) if f.endswith('.yaml') or f.endswith('.yml')]
        return {"files": files}
    except Exception as e:
        logger.error(f"Failed to list config files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Queue Management Endpoints
# -----------------------------------------------------------------------------

@app.post("/queue/deployment", response_model=QueueResponse)
async def add_to_queue(queue_request: QueueRequest):
    """Add a deployment request to the queue"""
    try:
        response = await queue_manager.add_to_queue(queue_request)
        return response
    except Exception as e:
        logger.error(f"Failed to add to queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/queue/list", response_model=List[QueueResponse])
async def get_queue_list():
    """Get list of all queue requests"""
    try:
        return await queue_manager.get_queue_list()
    except Exception as e:
        logger.error(f"Failed to get queue list: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/queue/status", response_model=QueueStatusResponse)
async def get_queue_status():
    """Get queue status overview"""
    try:
        return await queue_manager.get_queue_status()
    except Exception as e:
        logger.error(f"Failed to get queue status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/queue/{queue_request_id}", response_model=QueueResponse)
async def get_queue_request(queue_request_id: str):
    """Get specific queue request details"""
    try:
        queue_list = await queue_manager.get_queue_list()
        for request in queue_list:
            if request.queue_request_id == queue_request_id:
                return request
        raise HTTPException(status_code=404, detail="Queue request not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get queue request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/queue/{queue_request_id}")
async def delete_queue_request(queue_request_id: str, force: bool = False):
    """Delete a queue request"""
    try:
        success = await queue_manager.delete_queue_request(queue_request_id, force=force)
        if not success:
            if force:
                raise HTTPException(status_code=404, detail="Queue request not found")
            else:
                raise HTTPException(status_code=400, detail="Queue request not found or cannot be deleted (try with force=true for processing requests)")
        return {"message": f"Queue request {queue_request_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete queue request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/queue/{queue_request_id}/force")
async def force_delete_queue_request(queue_request_id: str):
    """Force delete a queue request regardless of status"""
    try:
        success = await queue_manager.force_delete_queue_request(queue_request_id)
        if not success:
            raise HTTPException(status_code=404, detail="Queue request not found")
        return {"message": f"Queue request {queue_request_id} force deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to force delete queue request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/queue/{queue_request_id}/cancel")
async def cancel_queue_request(queue_request_id: str):
    """Cancel a queue request (for processing requests)"""
    try:
        success = await queue_manager.cancel_queue_request(queue_request_id)
        if not success:
            raise HTTPException(status_code=404, detail="Queue request not found or cannot be cancelled")
        return {"message": f"Queue request {queue_request_id} cancelled successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel queue request: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/queue/{queue_request_id}/status")
async def update_queue_request_status(queue_request_id: str, update_data: Dict[str, Any]):
    """Update queue request status (used by benchmark-deployer for Helm deployments)"""
    try:
        success = await queue_manager.update_queue_request_status(queue_request_id, update_data)
        if not success:
            raise HTTPException(status_code=404, detail="Queue request not found")
        return {"message": f"Queue request {queue_request_id} status updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update queue request status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/queue/{queue_request_id}/priority")
async def change_queue_priority(queue_request_id: str, priority_request: QueuePriorityRequest):
    """Change priority of a queue request"""
    try:
        success = await queue_manager.change_queue_priority(queue_request_id, priority_request.priority)
        if not success:
            raise HTTPException(status_code=404, detail="Queue request not found or cannot change priority")
        return {"message": f"Queue request {queue_request_id} priority changed to {priority_request.priority}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to change queue priority: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Scheduler Management Endpoints
# -----------------------------------------------------------------------------

@app.post("/scheduler/start")
async def start_scheduler():
    """Start the queue scheduler"""
    try:
        await queue_manager.start_scheduler()
        return {"message": "Queue scheduler started successfully"}
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scheduler/stop")
async def stop_scheduler():
    """Stop the queue scheduler"""
    try:
        await queue_manager.stop_scheduler()
        return {"message": "Queue scheduler stopped successfully"}
    except Exception as e:
        logger.error(f"Failed to stop scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/scheduler/status")
async def get_scheduler_status():
    """Get detailed scheduler status"""
    try:
        return await queue_manager.get_scheduler_status()
    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scheduler/config")
async def update_scheduler_config(poll_interval: int = None):
    """Update scheduler configuration"""
    try:
        if poll_interval is not None:
            if poll_interval < 5:
                raise HTTPException(status_code=400, detail="Poll interval must be at least 5 seconds")
            if poll_interval > 3600:
                raise HTTPException(status_code=400, detail="Poll interval must be at most 3600 seconds (1 hour)")
            
            queue_manager.set_poll_interval(poll_interval)
            
        return {
            "message": "Scheduler configuration updated successfully",
            "poll_interval": queue_manager.poll_interval,
            "running": queue_manager.scheduler_running
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update scheduler config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scheduler/pause")
async def pause_scheduler():
    """Pause the queue scheduler (same as stop)"""
    try:
        await queue_manager.stop_scheduler()
        return {"message": "Queue scheduler paused successfully"}
    except Exception as e:
        logger.error(f"Failed to pause scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scheduler/resume")
async def resume_scheduler():
    """Resume the queue scheduler (same as start)"""
    try:
        await queue_manager.start_scheduler()
        return {"message": "Queue scheduler resumed successfully"}
    except Exception as e:
        logger.error(f"Failed to resume scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/last-custom-values")
async def get_last_custom_values_debug():
    """Debug endpoint to check last custom values tracking state"""
    return {
        "last_custom_values_hash": vllm_manager.last_custom_values_hash,
        "last_deployment_info": vllm_manager.last_deployment_info,
        "has_last_custom_values_content": bool(vllm_manager.last_custom_values_content),
        "custom_values_content_length": len(vllm_manager.last_custom_values_content) if vllm_manager.last_custom_values_content else 0
    }

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
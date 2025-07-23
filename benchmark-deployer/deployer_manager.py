import logging
import yaml
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid

def convert_github_api_to_clone_url(api_url: str) -> str:
    """Convert GitHub API URL to git clone URL"""
    if not api_url:
        return api_url
    
    # Handle API URL format: https://api.github.com/repos/owner/repo
    if "api.github.com/repos/" in api_url:
        # Extract owner/repo from API URL
        parts = api_url.replace("https://api.github.com/repos/", "").strip("/")
        if "/" in parts:
            return f"https://github.com/{parts}.git"
    
    # If already a clone URL, return as is
    if api_url.endswith('.git'):
        return api_url
    
    # Default fallback
    return api_url

# Import our modules
from config import DEFAULT_NAMESPACE, LOG_LEVEL, JOB_MAX_FAILURES, JOB_FAILURE_RETRY_DELAY, JOB_TIMEOUT
from models import (
    DeploymentRequest, DeploymentResponse, LogRequest, LogResponse,
    DeleteRequest, DeleteResponse, JobStatusResponse, ResourceType,
    TerminalSessionRequest, TerminalSessionResponse, TerminalSessionInfo, TerminalSessionListResponse,
    VLLMHelmDeploymentRequest, VLLMHelmConfig
)
from kubernetes_client import k8s_client
from terminal_manager import terminal_manager
from database import connect_to_mongo, get_deployments_collection

# Configure logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)

class DeployerManager:
    def __init__(self):
        self.mongo_client = None
        self.db = None
        self.processing_queue = False  # 큐 처리 중인지 확인하는 플래그

    async def initialize(self):
        """Initialize the deployer manager."""
        try:
            # Initialize MongoDB connection
            await connect_to_mongo()
            logger.info("MongoDB connection initialized")
            
            # Initialize our own MongoDB connection for queue operations
            from config import MONGO_URL, DB_NAME
            import motor.motor_asyncio
            self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(
                MONGO_URL,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )
            self.db = self.mongo_client[DB_NAME]
            logger.info("DeployerManager MongoDB connection initialized")
            
            # Initialize Kubernetes client
            await k8s_client.initialize()
            logger.info("Deployer manager initialized with Kubernetes connection")
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            # Re-raise the exception to prevent the service from starting without Kubernetes
            raise Exception(f"Failed to initialize deployer manager: Kubernetes client initialization failed: {str(e)}")

    async def deploy_yaml(self, request: DeploymentRequest) -> DeploymentResponse:
        """Deploy YAML content to Kubernetes."""
        try:
            # Check if Kubernetes client is connected
            if not k8s_client.is_connected:
                logger.error("Kubernetes client is not connected. Attempting to reconnect...")
                await k8s_client.initialize()
                
            namespace = request.namespace or DEFAULT_NAMESPACE
            
            # Parse and deploy YAML using Kubernetes client
            result = await k8s_client.deploy_yaml(
                yaml_content=request.yaml_content,
                namespace=namespace
            )
            
            # Store deployment info in database
            deployment_id = str(uuid.uuid4())
            deployment_doc = {
                "deployment_id": deployment_id,
                "resource_name": result["resource_name"],
                "resource_type": result["resource_type"].value if hasattr(result["resource_type"], 'value') else str(result["resource_type"]),
                "namespace": namespace,
                "yaml_content": request.yaml_content,
                "created_at": datetime.now(),
                "status": "deployed"
            }
            
            # Insert into database
            deployments_collection = get_deployments_collection()
            await deployments_collection.insert_one(deployment_doc)
            
            logger.info(f"Successfully deployed {result['resource_type']}: {result['resource_name']} in namespace {namespace}")
            
            return DeploymentResponse(
                status="success",
                message=f"Successfully deployed {result['resource_type']}: {result['resource_name']}",
                deployment_id=deployment_id,
                namespace=namespace,
                resource_type=result["resource_type"],
                resource_name=result["resource_name"],
                yaml_content=request.yaml_content,
                created_at=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            raise Exception(f"Deployment failed: {str(e)}")

    async def delete_yaml(self, request: DeleteRequest) -> DeleteResponse:
        """Delete Kubernetes resources from YAML content."""
        try:
            namespace = request.namespace or DEFAULT_NAMESPACE
            
            # Delete resources using Kubernetes client
            result = await k8s_client.delete_yaml(
                yaml_content=request.yaml_content,
                namespace=namespace
            )
            
            # Update deployment status in database
            deployments_collection = get_deployments_collection()
            await deployments_collection.update_many(
                {
                    "namespace": namespace,
                    "yaml_content": request.yaml_content,
                    "status": {"$ne": "deleted"}
                },
                {"$set": {"status": "deleted", "deleted_at": datetime.now()}}
            )
            
            logger.info(f"Successfully deleted {len(result['deleted_resources'])} resources in namespace {namespace}")
            
            return DeleteResponse(
                status="success",
                message=f"Successfully deleted {len(result['deleted_resources'])} resources",
                deleted_resources=result["deleted_resources"],
                namespace=namespace,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Deletion failed: {e}")
            raise Exception(f"Deletion failed: {str(e)}")

    async def get_job_logs(self, request: LogRequest) -> LogResponse:
        """Get logs from a job."""
        try:
            namespace = request.namespace or DEFAULT_NAMESPACE
            
            # Get logs using Kubernetes client
            logs = await k8s_client.get_job_logs(
                job_name=request.job_name,
                namespace=namespace,
                tail_lines=request.tail_lines,
                follow=request.follow
            )
            
            logger.info(f"Retrieved {len(logs)} log lines for job '{request.job_name}'")
            
            return LogResponse(
                job_name=request.job_name,
                namespace=namespace,
                logs=logs,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Failed to get job logs: {e}")
            raise Exception(f"Failed to get job logs: {str(e)}")

    async def get_job_status(self, job_name: str, namespace: str = DEFAULT_NAMESPACE) -> JobStatusResponse:
        """Get job status."""
        try:
            status = await k8s_client.get_job_status(job_name=job_name, namespace=namespace)
            
            logger.info(f"Retrieved status for job '{job_name}': {status.status}")
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            raise Exception(f"Failed to get job status: {str(e)}")

    async def list_active_deployments(self) -> List[Dict[str, Any]]:
        """List active deployments."""
        try:
            deployments = []
            
            # Get deployments from database
            deployments_collection = get_deployments_collection()
            cursor = deployments_collection.find({})
            
            async for doc in cursor:
                if "deleted_at" in doc:
                    continue
                    
                deployment = {
                    "deployment_id": doc["deployment_id"],
                    "resource_name": doc["resource_name"],
                    "resource_type": doc["resource_type"],
                    "namespace": doc["namespace"],
                    "created_at": doc["created_at"].isoformat(),
                    "status": doc.get("status", "unknown"),
                    "yaml_content": doc.get("yaml_content", "")
                }
                
                # Add deleted_at if present
                if "deleted_at" in doc:
                    deployment["deleted_at"] = doc["deleted_at"].isoformat()
                
                # Get current status from Kubernetes if not deleted
                if doc.get("status") != "deleted":
                    try:
                        current_status = None
                        
                        if doc["resource_type"] == "job":
                            status_response = await k8s_client.get_job_status(
                                job_name=doc["resource_name"],
                                namespace=doc["namespace"]
                            )
                            current_status = status_response.status.value
                            deployment["active_pods"] = status_response.active_pods
                            deployment["succeeded_pods"] = status_response.succeeded_pods
                            deployment["failed_pods"] = status_response.failed_pods
                            
                        elif doc["resource_type"] == "deployment":
                            current_status = await k8s_client.get_deployment_status(
                                deployment_name=doc["resource_name"],
                                namespace=doc["namespace"]
                            )
                            
                        elif doc["resource_type"] == "service":
                            current_status = await k8s_client.get_service_status(
                                service_name=doc["resource_name"],
                                namespace=doc["namespace"]
                            )
                            
                        else:
                            # For other resource types (configmap, secret, etc.), keep existing status
                            current_status = doc.get("status", "unknown")
                        
                        if current_status:
                            deployment["status"] = current_status
                            
                            # Update status in database if different
                            if doc.get("status") != current_status:
                                await deployments_collection.update_one(
                                    {"deployment_id": doc["deployment_id"]},
                                    {"$set": {"status": current_status}}
                                )
                                
                    except Exception as e:
                        deployment["status"] = "unknown"
                        deployment["error"] = str(e)
                
                # Skip unknown status deployments and mark them as deleted in DB
                if deployment["status"] == "unknown":
                    logger.warning(f"Deployment {doc['deployment_id']} has unknown status, marking as deleted in database")
                    await deployments_collection.update_one(
                        {"deployment_id": doc["deployment_id"]},
                        {"$set": {"status": "deleted", "deleted_at": datetime.now()}}
                    )
                    continue
                
                deployments.append(deployment)
            
            return deployments
            
        except Exception as e:
            logger.error(f"Failed to list deployments: {e}")
            raise Exception(f"Failed to list deployments: {str(e)}")

    async def get_system_health(self) -> Dict[str, Any]:
        """Get system health information."""
        try:
            k8s_health = await k8s_client.get_cluster_info()
            
            # Get active deployments count
            deployments_collection = get_deployments_collection()
            active_count = await deployments_collection.count_documents({"status": "deployed"})
            
            return {
                "service_status": "healthy",
                "kubernetes_connected": k8s_health is not None,
                "kubernetes_version": k8s_health.get("version") if k8s_health else None,
                "active_deployments": active_count
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "service_status": "unhealthy",
                "kubernetes_connected": False,
                "kubernetes_version": None,
                "active_deployments": 0
            }

    # -----------------------------------------------------------------------------
    # Terminal Session Methods
    # -----------------------------------------------------------------------------

    async def create_terminal_session(self, request: TerminalSessionRequest, host: str, port: int) -> TerminalSessionResponse:
        """Create a new terminal session for a job."""
        try:
            namespace = request.namespace or DEFAULT_NAMESPACE
            
            # Get pod information first
            pod_info = await k8s_client.get_job_pod_for_terminal(
                job_name=request.job_name,
                namespace=namespace,
                pod_name=request.pod_name
            )
            
            # Create terminal session
            session_id = await terminal_manager.create_session(
                job_name=request.job_name,
                namespace=namespace,
                pod_name=pod_info["pod_name"],
                container_name=request.container_name or pod_info["containers"][0],
                shell=request.shell or "/bin/bash"
            )
            
            websocket_url = f"ws://{host}:{port}/terminal/{session_id}"
            
            logger.info(f"Created terminal session {session_id} for job '{request.job_name}' on pod '{pod_info['pod_name']}'")
            
            return TerminalSessionResponse(
                session_id=session_id,
                job_name=request.job_name,
                namespace=namespace,
                pod_name=pod_info["pod_name"],
                container_name=request.container_name or pod_info["containers"][0],
                shell=request.shell or "/bin/bash",
                websocket_url=websocket_url,
                created_at=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Failed to create terminal session: {e}")
            raise Exception(f"Failed to create terminal session: {str(e)}")

    async def get_terminal_session(self, session_id: str) -> Optional[TerminalSessionInfo]:
        """Get terminal session information."""
        try:
            session = terminal_manager.get_session_info(session_id)
            
            if session:
                logger.info(f"Retrieved terminal session info for {session_id}")
                return TerminalSessionInfo(**session)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get terminal session: {e}")
            raise Exception(f"Failed to get terminal session: {str(e)}")

    async def list_terminal_sessions(self, job_name: Optional[str] = None) -> TerminalSessionListResponse:
        """List terminal sessions."""
        try:
            sessions_data = terminal_manager.list_sessions(job_name)
            
            sessions = [TerminalSessionInfo(**session) for session in sessions_data["sessions"]]
            
            logger.info(f"Listed {len(sessions)} terminal sessions")
            
            return TerminalSessionListResponse(
                sessions=sessions,
                total_sessions=sessions_data["total_sessions"],
                active_sessions=sessions_data["active_sessions"]
            )
            
        except Exception as e:
            logger.error(f"Failed to list terminal sessions: {e}")
            raise Exception(f"Failed to list terminal sessions: {str(e)}")

    async def stop_terminal_session(self, session_id: str):
        """Stop a terminal session."""
        try:
            await terminal_manager.stop_session(session_id)
            
            logger.info(f"Stopped terminal session {session_id}")
            
        except Exception as e:
            logger.error(f"Failed to stop terminal session: {e}")
            raise Exception(f"Failed to stop terminal session: {str(e)}")

    async def stop_job_terminal_sessions(self, job_name: str):
        """Stop all terminal sessions for a job."""
        try:
            stopped_count = await terminal_manager.stop_job_sessions(job_name)
            
            logger.info(f"Stopped {stopped_count} terminal sessions for job '{job_name}'")
            
        except Exception as e:
            logger.error(f"Failed to stop job terminal sessions: {e}")
            raise Exception(f"Failed to stop job terminal sessions: {str(e)}")

    async def cleanup_inactive_terminal_sessions(self, timeout_minutes: int = 30):
        """Clean up inactive terminal sessions."""
        try:
            cleaned_count = await terminal_manager.cleanup_inactive_sessions(timeout_minutes)
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} inactive terminal sessions")
                
        except Exception as e:
            logger.error(f"Failed to cleanup terminal sessions: {e}")

    # -----------------------------------------------------------------------------
    # VLLM Queue Management Methods (Integrated from benchmark-vllm)
    # -----------------------------------------------------------------------------

    async def add_vllm_to_queue(self, request: 'VLLMDeploymentQueueRequest') -> 'VLLMDeploymentQueueResponse':
        """Add a VLLM deployment + benchmark jobs request to the queue"""
        try:
            import uuid
            from models import VLLMDeploymentQueueResponse, SchedulingConfig
            
            queue_request_id = str(uuid.uuid4())
            
            # Calculate total steps: VLLM 생성을 건너뛰면 0, 아니면 1 + 벤치마크 작업 수
            total_steps = (0 if request.skip_vllm_creation else 1) + len(request.benchmark_configs)
            
            # Create queue request document
            queue_doc = {
                "queue_request_id": queue_request_id,
                "priority": request.priority,
                "status": "pending",
                "vllm_config": request.vllm_config.dict() if request.vllm_config else {},
                "benchmark_configs": [config.dict() for config in request.benchmark_configs],
                "scheduling_config": request.scheduling_config.dict() if request.scheduling_config else SchedulingConfig().dict(),
                "skip_vllm_creation": request.skip_vllm_creation,
                "created_at": datetime.now(),
                "started_at": None,
                "completed_at": None,
                "vllm_deployment_id": None,
                "benchmark_job_ids": [],
                "current_step": "pending",
                "total_steps": total_steps,
                "completed_steps": 0,
                "error_message": None
            }
            
            # Store in database
            await self._save_vllm_queue_request_to_db(queue_doc)
            
            logger.info(f"Added VLLM queue request {queue_request_id} with priority {request.priority}")
            
            return VLLMDeploymentQueueResponse(
                queue_request_id=queue_request_id,
                priority=request.priority,
                status="pending",
                vllm_config=request.vllm_config,
                benchmark_configs=request.benchmark_configs,
                scheduling_config=request.scheduling_config or SchedulingConfig(),
                created_at=queue_doc["created_at"],
                current_step="pending",
                total_steps=total_steps,
                completed_steps=0
            )
            
        except Exception as e:
            logger.error(f"Failed to add VLLM request to queue: {e}")
            raise Exception(f"Failed to add VLLM request to queue: {str(e)}")

    async def get_vllm_queue_list(self) -> List['VLLMDeploymentQueueResponse']:
        """Get list of all VLLM queue requests"""
        try:
            from models import VLLMDeploymentQueueResponse, VLLMConfig, BenchmarkJobConfig, SchedulingConfig
            
            # Get queue collection
            queue_collection = await self._get_vllm_queue_collection()
            
            result = []
            async for queue_doc in queue_collection.find().sort("created_at", -1):
                # Handle scheduling_config properly
                scheduling_config_data = queue_doc.get("scheduling_config", {})
                if scheduling_config_data:
                    scheduling_config = SchedulingConfig(**scheduling_config_data)
                else:
                    scheduling_config = SchedulingConfig()
                
                result.append(VLLMDeploymentQueueResponse(
                    queue_request_id=queue_doc["queue_request_id"],
                    priority=queue_doc["priority"],
                    status=queue_doc["status"],
                    vllm_config=VLLMConfig(**queue_doc["vllm_config"]) if queue_doc["vllm_config"] else None,
                    benchmark_configs=[BenchmarkJobConfig(**config) for config in queue_doc["benchmark_configs"]],
                    scheduling_config=scheduling_config,
                    created_at=queue_doc["created_at"],
                    started_at=queue_doc.get("started_at"),
                    completed_at=queue_doc.get("completed_at"),
                    vllm_deployment_id=queue_doc.get("vllm_deployment_id"),
                    benchmark_job_ids=queue_doc.get("benchmark_job_ids", []),
                    current_step=queue_doc.get("current_step", "pending"),
                    total_steps=queue_doc.get("total_steps", 1),
                    completed_steps=queue_doc.get("completed_steps", 0),
                    error_message=queue_doc.get("error_message")
                ))
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get VLLM queue list: {e}")
            raise Exception(f"Failed to get VLLM queue list: {str(e)}")

    async def get_vllm_queue_status(self) -> 'VLLMQueueStatusResponse':
        """Get VLLM queue status overview"""
        try:
            from models import VLLMQueueStatusResponse
            
            queue_collection = await self._get_vllm_queue_collection()
            
            status_counts = {
                "pending": 0,
                "processing": 0, 
                "completed": 0,
                "failed": 0,
                "cancelled": 0
            }
            
            async for queue_doc in queue_collection.find():
                status = queue_doc["status"]
                if status in status_counts:
                    status_counts[status] += 1
            
            return VLLMQueueStatusResponse(
                total_requests=sum(status_counts.values()),
                pending_requests=status_counts["pending"],
                processing_requests=status_counts["processing"],
                completed_requests=status_counts["completed"],
                failed_requests=status_counts["failed"],
                cancelled_requests=status_counts["cancelled"]
            )
            
        except Exception as e:
            logger.error(f"Failed to get VLLM queue status: {e}")
            raise Exception(f"Failed to get VLLM queue status: {str(e)}")

    async def cancel_vllm_queue_request(self, queue_request_id: str) -> bool:
        """Cancel a VLLM queue request and clean up resources"""
        try:
            logger.info(f"Attempting to cancel VLLM queue request {queue_request_id}")
            
            # Get queue collection
            queue_collection = await self._get_vllm_queue_collection()
            
            # Find the queue request
            queue_request = await queue_collection.find_one({"queue_request_id": queue_request_id})
            if not queue_request:
                logger.warning(f"Queue request {queue_request_id} not found")
                return False
            
            # Only allow cancellation of pending or processing requests
            if queue_request.get("status") not in ["pending", "processing"]:
                logger.warning(f"Cannot cancel queue request {queue_request_id} with status {queue_request.get('status')}")
                return False
            
            logger.info(f"Cancelling queue request {queue_request_id} with status {queue_request.get('status')}")
            
            # Clean up resources if processing
            if queue_request.get("status") == "processing":
                await self._cleanup_processing_vllm_request(queue_request_id, queue_request)
            
            # Update status to cancelled
            await queue_collection.update_one(
                {"queue_request_id": queue_request_id},
                {
                    "$set": {
                        "status": "cancelled",
                        "completed_at": datetime.now(),
                        "error_message": "Cancelled by user"
                    }
                }
            )
            
            logger.info(f"Successfully cancelled VLLM queue request {queue_request_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling VLLM queue request {queue_request_id}: {e}")
            return False

    async def _cleanup_processing_vllm_request(self, queue_request_id: str, queue_request: dict):
        """Clean up resources for a processing VLLM request"""
        try:
            logger.info(f"Cleaning up processing VLLM request {queue_request_id}")
            
            # 1. Clean up benchmark jobs using multiple methods
            await self._cleanup_benchmark_jobs_comprehensive(queue_request_id, queue_request)
            
            # 2. Clean up VLLM deployment if it was created by this request
            await self._cleanup_vllm_deployment_for_request(queue_request_id, queue_request)
            
        except Exception as e:
            logger.error(f"Error during cleanup of processing VLLM request {queue_request_id}: {e}")

    async def _cleanup_benchmark_jobs_comprehensive(self, queue_request_id: str, queue_request: dict):
        """Comprehensive cleanup of benchmark jobs using multiple methods"""
        try:
            # Method 1: Clean up using benchmark_job_ids (existing method)
            benchmark_job_ids = queue_request.get("benchmark_job_ids", [])
            if benchmark_job_ids:
                logger.info(f"Cleaning up {len(benchmark_job_ids)} benchmark jobs by job IDs")
                for job_id in benchmark_job_ids:
                    try:
                        # Try to get job name from deployments collection
                        deployments_collection = get_deployments_collection()
                        deployment_doc = await deployments_collection.find_one({"deployment_id": job_id})
                        
                        if deployment_doc:
                            job_name = deployment_doc.get("resource_name")
                            namespace = deployment_doc.get("namespace", "default")
                            
                            if job_name:
                                logger.info(f"Deleting benchmark job {job_name} in namespace {namespace}")
                                await self.delete_job(job_name, namespace)
                        
                    except Exception as e:
                        logger.warning(f"Error cleaning up benchmark job {job_id}: {e}")
                        continue
            
            # Method 2: Clean up using created_job_names if available
            created_job_names = queue_request.get("created_job_names", [])
            if created_job_names:
                logger.info(f"Cleaning up {len(created_job_names)} jobs by stored names")
                for job_info in created_job_names:
                    try:
                        if isinstance(job_info, dict):
                            job_name = job_info.get('name')
                            namespace = job_info.get('namespace', 'default')
                        else:
                            job_name = job_info
                            namespace = 'default'
                        
                        if job_name:
                            logger.info(f"Deleting stored job {job_name} in namespace {namespace}")
                            await self.delete_job(job_name, namespace)
                    except Exception as e:
                        logger.warning(f"Error cleaning up stored job {job_info}: {e}")
                        continue
            
            # Method 3: Search for jobs related to this queue request
            await self._cleanup_jobs_by_pattern(queue_request_id)
            
        except Exception as e:
            logger.error(f"Error during comprehensive benchmark job cleanup: {e}")

    async def _cleanup_jobs_by_pattern(self, queue_request_id: str):
        """Search and clean up jobs that might be related to this queue request"""
        try:
            logger.info(f"Searching for jobs related to queue request {queue_request_id}")
            
            # Get all active deployments and look for jobs that might be related
            deployments_collection = get_deployments_collection()
            
            # Find jobs that might be related (by name patterns or timing)
            related_jobs = await deployments_collection.find({
                "resource_type": {"$in": ["job", "Job"]},
                "status": {"$nin": ["deleted", "completed"]},
                "$or": [
                    {"resource_name": {"$regex": f".*{queue_request_id[:8]}.*", "$options": "i"}},  # Partial UUID match
                    {"resource_name": {"$regex": "benchmark.*", "$options": "i"}},  # Benchmark pattern
                    {"yaml_content": {"$regex": f".*{queue_request_id}.*", "$options": "i"}}  # Queue ID in YAML
                ]
            }).to_list(length=None)
            
            if related_jobs:
                logger.info(f"Found {len(related_jobs)} potentially related jobs for cleanup")
                for job_doc in related_jobs:
                    try:
                        job_name = job_doc.get("resource_name")
                        namespace = job_doc.get("namespace", "default")
                        
                        if job_name:
                            logger.info(f"Deleting potentially related job {job_name} in namespace {namespace}")
                            await self.delete_job(job_name, namespace)
                    except Exception as e:
                        logger.warning(f"Error cleaning up related job {job_doc.get('resource_name')}: {e}")
                        continue
            else:
                logger.info(f"No additional related jobs found for queue request {queue_request_id}")
                
        except Exception as e:
            logger.warning(f"Error during pattern-based job cleanup: {e}")

    async def _cleanup_vllm_deployment_for_request(self, queue_request_id: str, queue_request: dict):
        """Clean up VLLM deployment if it was created by this request"""
        try:
            vllm_deployment_id = queue_request.get("vllm_deployment_id")
            if vllm_deployment_id and vllm_deployment_id != "existing-vllm":
                logger.info(f"Cleaning up VLLM deployment {vllm_deployment_id}")
                
                # Check if other requests are using this deployment
                other_requests = await self._get_vllm_queue_collection().find({
                    "vllm_deployment_id": vllm_deployment_id,
                    "queue_request_id": {"$ne": queue_request_id},
                    "status": {"$in": ["pending", "processing"]}
                }).to_list(length=None)
                
                if not other_requests:
                    # No other requests using this deployment, safe to delete
                    try:
                        # Call VLLM service to stop deployment
                        import aiohttp
                        from config import BENCHMARK_VLLM_URL
                        
                        async with aiohttp.ClientSession() as session:
                            delete_url = f"{BENCHMARK_VLLM_URL}/deployments/{vllm_deployment_id}"
                            async with session.delete(delete_url) as response:
                                if response.status in [200, 204, 404]:
                                    logger.info(f"Successfully deleted VLLM deployment {vllm_deployment_id}")
                                else:
                                    error_text = await response.text()
                                    logger.warning(f"Failed to delete VLLM deployment: HTTP {response.status} - {error_text}")
                    
                    except Exception as e:
                        logger.warning(f"Error deleting VLLM deployment {vllm_deployment_id}: {e}")
                else:
                    logger.info(f"VLLM deployment {vllm_deployment_id} is used by {len(other_requests)} other requests, not deleting")
            else:
                logger.info(f"No VLLM deployment to clean up for request {queue_request_id} (deployment_id: {vllm_deployment_id})")
            
            logger.info(f"Completed VLLM cleanup for request {queue_request_id}")
            
        except Exception as e:
            logger.error(f"Error during VLLM deployment cleanup for request {queue_request_id}: {e}")

    async def change_vllm_queue_priority(self, queue_request_id: str, new_priority: str) -> bool:
        """Change priority of a VLLM queue request"""
        try:
            queue_collection = await self._get_vllm_queue_collection()
            
            result = await queue_collection.update_one(
                {"queue_request_id": queue_request_id, "status": "pending"},
                {"$set": {"priority": new_priority}}
            )
            
            if result.modified_count > 0:
                logger.info(f"Changed priority of VLLM queue request {queue_request_id} to {new_priority}")
                return True
            else:
                logger.warning(f"VLLM queue request {queue_request_id} not found or not pending")
                return False
                
        except Exception as e:
            logger.error(f"Failed to change priority for VLLM queue request {queue_request_id}: {e}")
            return False

    # -----------------------------------------------------------------------------
    # VLLM Queue Helper Methods
    # -----------------------------------------------------------------------------

    async def _save_vllm_queue_request_to_db(self, queue_doc: Dict[str, Any]):
        """Save VLLM queue request to database"""
        try:
            queue_collection = await self._get_vllm_queue_collection()
            await queue_collection.insert_one(queue_doc)
        except Exception as e:
            logger.error(f"Failed to save VLLM queue request to database: {e}")
            raise

    async def _get_vllm_queue_collection(self):
        """Get VLLM queue collection from database"""
        from database import get_database
        db = get_database()
        return db.vllm_deployment_queue

    # -----------------------------------------------------------------------------
    # VLLM Queue Scheduler Methods
    # -----------------------------------------------------------------------------

    async def process_vllm_queue(self):
        """Process pending VLLM queue requests"""
        # 이미 큐 처리 중이면 건너뛰기 (동시 처리 방지)
        if self.processing_queue:
            logger.info("Queue processing already in progress, skipping...")
            return
            
        try:
            self.processing_queue = True
            logger.info("Starting VLLM queue processing cycle...")
            queue_collection = await self._get_vllm_queue_collection()
            
            # 현재 처리 중인 요청이 있는지 확인
            processing_request = await queue_collection.find_one({"status": "processing"})
            if processing_request:
                logger.info(f"Request {processing_request['queue_request_id']} is currently processing, waiting...")
                return
            
            # Get pending requests sorted by priority and creation time
            priority_order = {"urgent": 4, "high": 3, "medium": 2, "low": 1}
            
            pending_requests = []
            total_requests = await queue_collection.count_documents({})
            pending_count = await queue_collection.count_documents({"status": "pending"})
            processing_count = await queue_collection.count_documents({"status": "processing"})
            
            logger.info(f"Queue status: Total={total_requests}, Pending={pending_count}, Processing={processing_count}")
            
            async for request in queue_collection.find({"status": "pending"}).sort("created_at", 1):
                request["_priority_score"] = priority_order.get(request["priority"], 1)
                pending_requests.append(request)
                logger.info(f"Found pending request: {request['queue_request_id']} (priority: {request['priority']})")
            
            if not pending_requests:
                logger.info("No pending requests in queue")
                return
            
            # Sort by priority (high to low) then by creation time (old to new)
            pending_requests.sort(key=lambda x: (-x["_priority_score"], x["created_at"]))
            
            # 한 번에 하나의 요청만 처리 (순차 처리 보장)
            request = pending_requests[0]
            logger.info(f"Processing queue request {request['queue_request_id']} (priority: {request['priority']})")
            
            try:
                await self._process_single_vllm_request(request)
            except Exception as e:
                logger.error(f"Failed to process VLLM queue request {request['queue_request_id']}: {e}")
                await self._mark_request_failed(request["queue_request_id"], str(e))
                    
        except Exception as e:
            logger.error(f"Failed to process VLLM queue: {e}")
        finally:
            self.processing_queue = False

    async def _process_single_vllm_request(self, request):
        """Process a single VLLM queue request"""
        queue_request_id = request["queue_request_id"]
        skip_vllm_creation = request.get("skip_vllm_creation", False)
        
        try:
            # Mark as processing immediately when starting
            await self._update_request_status(queue_request_id, "processing", 
                                            "benchmark_jobs" if skip_vllm_creation else "vllm_deployment")
            
            # Step 1: Deploy VLLM (건너뛰기 옵션이 활성화되지 않은 경우에만)
            if skip_vllm_creation:
                logger.info(f"Skipping VLLM creation for request {queue_request_id} - using existing VLLM")
                # 기존 VLLM 작업을 완전히 건너뛰고 플레이스홀더만 설정
                vllm_deployment_info = {"deployment_id": "existing-vllm"}
                logger.info(f"VLLM creation skipped, proceeding with benchmark jobs only")
            else:
                # VLLM 배포 시작 시 상태를 즉시 processing으로 변경
                await self._update_request_status(queue_request_id, "processing", "vllm_deployment")
                
                # Check if vllm_config is valid before deploying
                if not request["vllm_config"] or not request["vllm_config"].get("model_name"):
                    raise Exception("Invalid or empty VLLM configuration")
                
                vllm_deployment_info = await self._deploy_vllm_from_config(request["vllm_config"])
                # Update with VLLM deployment ID
                await self._update_request_with_vllm_deployment(queue_request_id, vllm_deployment_info["deployment_id"])
                # VLLM 배포 완료 시 스텝 증가
                await self._increment_completed_steps(queue_request_id)
            
            # Step 2: Process benchmark jobs
            benchmark_job_ids = []
            benchmark_configs = request.get("benchmark_configs", [])
            
            if benchmark_configs:
                for i, benchmark_config in enumerate(benchmark_configs):
                    try:
                        await self._update_request_status(
                            queue_request_id, 
                            "processing", 
                            f"benchmark_job_{i+1}_deploying"
                        )
                        
                        # Deploy benchmark job
                        job_deployment_id = await self._deploy_benchmark_job(
                            benchmark_config, 
                            vllm_deployment_info
                        )
                        benchmark_job_ids.append(job_deployment_id)
                        
                        # Update status to running
                        await self._update_request_status(
                            queue_request_id, 
                            "processing", 
                            f"benchmark_job_{i+1}_running"
                        )
                        
                        # Wait for the job to complete before proceeding to next one
                        await self._wait_for_deployed_job_completion(
                            job_deployment_id=job_deployment_id,
                            namespace=benchmark_config.get("namespace", "default"),
                            timeout=3600  # 1 hour timeout per job
                        )
                        
                        # Update progress
                        await self._increment_completed_steps(queue_request_id)
                        logger.info(f"Completed benchmark job {i+1}/{len(benchmark_configs)} for request {queue_request_id}")
                        
                    except Exception as e:
                        logger.error(f"Failed to deploy benchmark job {i+1} for request {queue_request_id}: {e}")
                        # Continue with other jobs even if one fails
            else:
                logger.info(f"No benchmark jobs to process for request {queue_request_id}")
            
            # Mark as completed only after all steps are done
            await self._mark_request_completed(queue_request_id, benchmark_job_ids)
            logger.info(f"Request {queue_request_id} completed successfully with {len(benchmark_job_ids)} benchmark jobs")
            
        except Exception as e:
            await self._mark_request_failed(queue_request_id, str(e))
            raise



    async def _deploy_vllm_from_config(self, vllm_config):
        """Deploy VLLM using Helm configuration"""
        from models import VLLMHelmDeploymentRequest, VLLMHelmConfig, VLLMConfig
        
        # Convert dict to VLLMConfig object
        config = VLLMConfig(**vllm_config)
        
        # Create clean model name for consistent naming (no timestamp)
        clean_model_name = config.model_name.replace('/', '-').replace('_', '-').lower()
        release_name = f"vllm-{clean_model_name}"
        
        # Create Helm deployment request with fixed Pod naming
        helm_config = VLLMHelmConfig(
            release_name=release_name,
            chart_path="./benchmark-vllm-helm/charts/thaki/vllm",
            namespace=config.namespace,
            project_id=None,  # No custom values file for queue deployments
            values_file_id=None,
            additional_args=f"--set vllm.model={config.model_name} --set fullnameOverride=vllm-{clean_model_name} --set resources.limits.{config.gpu_resource_type}={config.gpu_resource_count} --set resources.requests.{config.gpu_resource_type}={config.gpu_resource_count}"
        )
        
        helm_request = VLLMHelmDeploymentRequest(
            vllm_config=config,
            vllm_helm_config=helm_config
        )
        
        # Deploy using Helm
        result = await self.deploy_vllm_with_helm(helm_request)
        
        # Return the actual release name for proper service name mapping
        return {
            "deployment_id": result["deployment_id"],
            "release_name": release_name,
            "service_name": f"{release_name}-service",
            "namespace": config.namespace
        }

    async def _deploy_benchmark_job(self, benchmark_config, vllm_deployment_info):
        """Deploy a benchmark job"""
        from models import DeploymentRequest
        
        # Replace placeholders in YAML
        yaml_content = benchmark_config["yaml_content"]
        
        # 기존 VLLM 사용 시 플레이스홀더를 그대로 유지 (사용자가 YAML에서 직접 처리)
        if vllm_deployment_info["deployment_id"] == "existing-vllm":
            logger.info("Using existing VLLM - placeholders in YAML will remain unchanged for user to configure")
            # 플레이스홀더를 그대로 두어 사용자가 직접 실제 서비스 이름으로 교체하도록 함
        else:
            # 새로 배포된 VLLM의 경우 실제 Helm 릴리스 정보를 사용
            service_name = vllm_deployment_info.get("service_name", f"vllm-service-{vllm_deployment_info['deployment_id'][:8]}")
            release_name = vllm_deployment_info.get("release_name", f"vllm-{vllm_deployment_info['deployment_id'][:8]}")
            pod_name = f"{release_name}-0"  # StatefulSet pod name is predictable
            
            logger.info(f"Replacing placeholders: VLLM_SERVICE_NAME -> {service_name}, VLLM_DEPLOYMENT_NAME -> {release_name}, VLLM_POD_NAME -> {pod_name}")
            
            yaml_content = yaml_content.replace("VLLM_DEPLOYMENT_NAME", release_name)
            yaml_content = yaml_content.replace("VLLM_SERVICE_NAME", service_name)
            yaml_content = yaml_content.replace("VLLM_POD_NAME", pod_name)
        
        # Create deployment request
        deployment_request = DeploymentRequest(
            yaml_content=yaml_content,
            namespace=benchmark_config.get("namespace", "default")
        )
        
        # Deploy the job
        deployment_response = await self.deploy_yaml(deployment_request)
        
        job_name = benchmark_config.get("name", "benchmark-job")
        logger.info(f"Successfully deployed benchmark job '{job_name}': {deployment_response.resource_name}")
        return deployment_response.deployment_id

    # Queue status update methods
    async def _update_request_status(self, queue_request_id, status, current_step=None):
        update_data = {
            "status": status,
            "started_at": datetime.now() if status == "processing" else None
        }
        if current_step:
            update_data["current_step"] = current_step
            
        queue_collection = await self._get_vllm_queue_collection()
        await queue_collection.update_one(
            {"queue_request_id": queue_request_id},
            {"$set": update_data}
        )

    async def _update_request_with_vllm_deployment(self, queue_request_id, vllm_deployment_id):
        queue_collection = await self._get_vllm_queue_collection()
        await queue_collection.update_one(
            {"queue_request_id": queue_request_id},
            {"$set": {"vllm_deployment_id": vllm_deployment_id}}
        )

    async def _increment_completed_steps(self, queue_request_id):
        queue_collection = await self._get_vllm_queue_collection()
        await queue_collection.update_one(
            {"queue_request_id": queue_request_id},
            {"$inc": {"completed_steps": 1}}
        )

    async def _mark_request_completed(self, queue_request_id, benchmark_job_ids):
        queue_collection = await self._get_vllm_queue_collection()
        await queue_collection.update_one(
            {"queue_request_id": queue_request_id},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.now(),
                "benchmark_job_ids": benchmark_job_ids,
                "current_step": "completed"
            }}
        )

    async def _mark_request_failed(self, queue_request_id, error_message):
        queue_collection = await self._get_vllm_queue_collection()
        await queue_collection.update_one(
            {"queue_request_id": queue_request_id},
            {"$set": {
                "status": "failed",
                "completed_at": datetime.now(),
                "error_message": error_message,
                "current_step": "failed"
            }}
        )
        logger.info(f"Marked queue request {queue_request_id} as failed: {error_message}")



    async def deploy_vllm_with_helm(self, request: VLLMHelmDeploymentRequest) -> Dict[str, Any]:
        try:
            import aiohttp
            import tempfile
            import os
            import subprocess
            import asyncio
            
            # Check if VLLM creation should be skipped
            skip_vllm_creation = getattr(request, 'skip_vllm_creation', False)
            
            if skip_vllm_creation:
                logger.info(f"VLLM creation is skipped - redirecting to queue deployment for benchmark jobs only")
                
                # Convert to queue request and process via queue
                from models import VLLMDeploymentQueueRequest
                queue_request = VLLMDeploymentQueueRequest(
                    vllm_config=None,  # No config when skipping VLLM creation
                    benchmark_configs=request.benchmark_configs or [],
                    scheduling_config=request.scheduling_config or {},
                    priority=request.priority,
                    skip_vllm_creation=True
                )
                
                # Add to queue instead of deploying
                queue_response = await self.add_vllm_to_queue(queue_request)
                
                return {
                    "status": "success",
                    "message": f"Benchmark jobs added to queue (VLLM creation skipped)",
                    "deployment_id": "skipped-vllm",
                    "queue_request_id": queue_response.queue_request_id,
                    "action": "queued"
                }
            
            logger.info(f"Starting VLLM Helm deployment: {request.vllm_helm_config.release_name}")
            
            # Get GitHub token first for queue registration
            github_token = None
            if request.vllm_helm_config.project_id:
                logger.info(f"Fetching GitHub token for project: {request.vllm_helm_config.project_id}")
                from config import BENCHMARK_MANAGER_URL
                async with aiohttp.ClientSession() as session:
                    project_url = f"{BENCHMARK_MANAGER_URL}/projects/{request.vllm_helm_config.project_id}"
                    async with session.get(project_url) as response:
                        if response.status == 200:
                            project_data = await response.json()
                            # Manager returns ProjectWithStats, so github_token is in project.github_token
                            project_info = project_data.get('project', {})
                            github_token = project_info.get('github_token')
                            if github_token:
                                logger.info(f"Retrieved GitHub token for project {request.vllm_helm_config.project_id}")
                            else:
                                logger.warning(f"No GitHub token found in project {request.vllm_helm_config.project_id}")
                        else:
                            logger.warning(f"Failed to fetch project information: {response.status}")
            
            # Get custom values file content if specified (GitHub token already retrieved above)
            values_content = None
            if request.vllm_helm_config.project_id and request.vllm_helm_config.values_file_id:
                values_content = await self._get_values_file_content(
                    request.vllm_helm_config.project_id, 
                    request.vllm_helm_config.values_file_id,
                    github_token
                )
            
            # Register this Helm deployment request in the benchmark-vllm queue
            queue_request_id = await self._register_helm_deployment_in_queue(request, github_token, values_content)
            
            # Create temporary values file
            values_file_path = None
            if values_content:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                    f.write(values_content)
                    values_file_path = f.name
                    logger.info(f"Created temporary values file: {values_file_path}")
            
            try:
                # deployer는 Helm 배포를 하지 않고 benchmark-vllm 큐에 요청만 등록
                logger.info("Helm deployment request registered in benchmark-vllm queue. Actual deployment will be handled by benchmark-vllm service.")
                
                return {
                    "status": "success", 
                    "message": "VLLM Helm deployment request registered in queue successfully",
                    "deployment_id": "queued",
                    "queue_request_id": queue_request_id,
                    "action": "queued"
                }
                    
            finally:
                # Clean up temporary values file
                if values_file_path and os.path.exists(values_file_path):
                    os.unlink(values_file_path)
                    logger.info(f"Cleaned up temporary values file: {values_file_path}")
                    
        except Exception as e:
            logger.error(f"VLLM Helm deployment failed: {e}")
            raise Exception(f"VLLM Helm deployment failed: {str(e)}")

    async def _register_helm_deployment_in_queue(self, request: VLLMHelmDeploymentRequest, github_token: str = None, values_content: str = None):
        """Register Helm deployment request in the benchmark-vllm queue for visibility"""
        try:
            import aiohttp
            from config import BENCHMARK_VLLM_URL, BENCHMARK_MANAGER_URL
            
            logger.info("Registering Helm deployment in benchmark-vllm queue...")
            
            # Get project repository URL if project_id is provided
            repository_url = None
            if request.vllm_helm_config.project_id:
                async with aiohttp.ClientSession() as session:
                    project_url = f"{BENCHMARK_MANAGER_URL}/projects/{request.vllm_helm_config.project_id}"
                    async with session.get(project_url) as response:
                        if response.status == 200:
                            project_data = await response.json()
                            project_info = project_data.get('project', {})
                            repository_url = project_info.get('repository_url')
                            logger.info(f"Retrieved repository URL: {repository_url}")
            
            # Add custom values to vllm_config if available
            vllm_config_dict = request.vllm_config.dict() if request.vllm_config else {}
            if values_content:
                vllm_config_dict["custom_values_content"] = values_content
                logger.info(f"Added custom values content to VLLM config for queue (size: {len(values_content)} chars)")
            
            # Prepare queue request data compatible with benchmark-vllm QueueRequest model
            queue_request_data = {
                "vllm_config": vllm_config_dict,
                "benchmark_configs": request.benchmark_configs or [],
                "scheduling_config": request.scheduling_config or {
                    "immediate": True,
                    "scheduled_time": None,
                    "max_wait_time": 3600
                },
                "priority": request.priority,
                "vllm_yaml_content": None,
                # Add Helm-specific metadata
                "helm_deployment": True,
                "helm_config": request.vllm_helm_config.dict(),
                # Add GitHub token for private repository access
                "github_token": github_token,
                # Add repository URL for charts cloning
                "repository_url": repository_url
            }
            
            async with aiohttp.ClientSession() as session:
                queue_url = f"{BENCHMARK_VLLM_URL}/queue/deployment"
                async with session.post(queue_url, json=queue_request_data) as response:
                    if response.status == 200:
                        queue_response = await response.json()
                        logger.info(f"Successfully registered Helm deployment in queue: {queue_response.get('queue_request_id')}")
                        return queue_response.get('queue_request_id')
                    else:
                        error_text = await response.text()
                        logger.warning(f"Failed to register Helm deployment in queue: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.warning(f"Failed to register Helm deployment in queue: {e}")
            # Don't fail the deployment if queue registration fails
            return None







    async def _update_queue_status(self, queue_request_id: str, status: str, deployment_id: str = None, error_message: str = None):
        """Update queue status in benchmark-vllm service"""
        try:
            import aiohttp
            from config import BENCHMARK_VLLM_URL
            
            logger.info(f"Updating queue status for {queue_request_id}: {status}")
            
            # Prepare update data
            update_data = {
                "status": status,
                "completed_at": datetime.now().isoformat()
            }
            
            if deployment_id:
                update_data["deployment_id"] = deployment_id
                
            if error_message:
                update_data["error_message"] = error_message
            
            async with aiohttp.ClientSession() as session:
                update_url = f"{BENCHMARK_VLLM_URL}/queue/{queue_request_id}/status"
                async with session.patch(update_url, json=update_data) as response:
                    if response.status == 200:
                        logger.info(f"Successfully updated queue status for {queue_request_id}")
                    else:
                        error_text = await response.text()
                        logger.warning(f"Failed to update queue status: {response.status} - {error_text}")
                        
        except Exception as e:
            logger.warning(f"Failed to update queue status for {queue_request_id}: {e}")
            # Don't fail the deployment if queue update fails

    async def _execute_helm_benchmark_jobs(self, benchmark_configs: List[Dict[str, Any]], deployment_id: str):
        """Execute benchmark jobs for Helm deployment"""
        logger.info(f"Executing {len(benchmark_configs)} benchmark jobs for Helm deployment {deployment_id}")
        
        for i, config in enumerate(benchmark_configs):
            job_name = config.get('name', f'helm-benchmark-job-{i+1}')
            yaml_content = config.get('yaml_content', '')
            namespace = config.get('namespace', 'default')
            
            logger.info(f"Executing benchmark job {i+1}/{len(benchmark_configs)}: {job_name}")
            
            try:
                # Create deployment request using the same logic as _deploy_benchmark_job
                from models import DeploymentRequest
                
                deployment_request = DeploymentRequest(
                    yaml_content=yaml_content,
                    namespace=namespace
                )
                
                # Deploy the benchmark job using existing deployment logic
                deployment_result = await self.deploy_yaml(deployment_request)
                
                # Wait for the job to complete
                actual_job_name = deployment_result.resource_name
                await self._wait_for_benchmark_job_completion(
                    job_name=actual_job_name,
                    namespace=namespace,
                    timeout=JOB_TIMEOUT,
                    max_failures=JOB_MAX_FAILURES
                )
                
                logger.info(f"Benchmark job {actual_job_name} completed successfully")
                
            except Exception as e:
                logger.error(f"Failed to execute benchmark job {job_name}: {e}")
                # Continue with next job even if current one fails
                continue
        
        logger.info(f"Completed execution of {len(benchmark_configs)} benchmark jobs")

    async def _wait_for_benchmark_job_completion(self, job_name: str, namespace: str, timeout: int = 3600, max_failures: int = 3):
        """Wait for a benchmark job to complete with failure tracking"""
        import asyncio
        from datetime import datetime
        
        start_time = datetime.now()
        failure_count = 0
        consecutive_failures = 0
        last_status = None
        
        while True:
            try:
                # Get job status
                status_data = await self.get_job_status(job_name, namespace)
                job_status = status_data.get('status', '').lower()
                
                logger.debug(f"Job {job_name} status: {job_status}")
                
                if job_status in ['completed', 'succeeded']:
                    logger.info(f"Job {job_name} completed successfully")
                    return
                
                if job_status in ['failed', 'error']:
                    failure_count += 1
                    consecutive_failures += 1
                    
                    logger.warning(f"Job {job_name} failed with status: {job_status} (failure #{failure_count})")
                    
                    # Check if we've exceeded maximum failures
                    if failure_count >= max_failures:
                        logger.error(f"Job {job_name} has failed {failure_count} times, exceeding maximum of {max_failures}. Terminating job.")
                        
                        # Attempt to delete the failed job
                        try:
                            await self._terminate_failed_job(job_name, namespace)
                            logger.info(f"Successfully terminated failed job {job_name}")
                        except Exception as terminate_error:
                            logger.error(f"Failed to terminate job {job_name}: {terminate_error}")
                        
                        raise Exception(f"Job {job_name} failed {failure_count} times, exceeding maximum failures ({max_failures}). Job has been terminated.")
                    
                    # Wait longer before retrying after failure
                    logger.info(f"Job {job_name} failed, waiting {JOB_FAILURE_RETRY_DELAY} seconds before next check...")
                    await asyncio.sleep(JOB_FAILURE_RETRY_DELAY)
                    continue
                
                # Reset consecutive failures if job is running again
                if job_status in ['running', 'pending'] and last_status in ['failed', 'error']:
                    consecutive_failures = 0
                    logger.info(f"Job {job_name} is recovering from failure")
                
                last_status = job_status
            
            except Exception as e:
                # Don't count connection/API errors as job failures
                if "failed with status" in str(e) and "exceeding maximum failures" in str(e):
                    # This is our termination exception, re-raise it
                    raise e
                else:
                    # This is a connection/API error, log but don't count as failure
                    logger.warning(f"Error checking job {job_name} status: {e}")
            
            # Check timeout
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.error(f"Timeout waiting for job {job_name} to complete after {elapsed}s (timeout: {timeout}s)")
                
                # Attempt to terminate the timed-out job
                try:
                    await self._terminate_failed_job(job_name, namespace)
                    logger.info(f"Successfully terminated timed-out job {job_name}")
                except Exception as terminate_error:
                    logger.error(f"Failed to terminate timed-out job {job_name}: {terminate_error}")
                
                raise Exception(f"Timeout waiting for job {job_name} to complete (timeout: {timeout}s). Job has been terminated.")
            
            # Wait before next check
            await asyncio.sleep(30)  # Check every 30 seconds

    async def _terminate_failed_job(self, job_name: str, namespace: str):
        """Terminate a failed job by deleting it from Kubernetes"""
        try:
            logger.info(f"Attempting to terminate job {job_name} in namespace {namespace}")
            
            # Use Kubernetes client to delete the job
            success = await k8s_client.delete_job(job_name, namespace)
            
            if success:
                logger.info(f"Job {job_name} terminated successfully")
                
                # Update deployment status in database
                deployments_collection = get_deployments_collection()
                await deployments_collection.update_many(
                    {
                        "resource_name": job_name,
                        "namespace": namespace,
                        "resource_type": {"$in": ["job", "Job"]},
                        "status": {"$ne": "deleted"}
                    },
                    {"$set": {"status": "terminated", "terminated_at": datetime.now()}}
                )
                logger.info(f"Updated database status for terminated job {job_name}")
            else:
                logger.warning(f"Failed to terminate job {job_name} - job may not exist")
                
        except Exception as e:
            logger.error(f"Error terminating job {job_name}: {e}")
            raise e

    async def _wait_for_deployed_job_completion(self, job_deployment_id: str, namespace: str, timeout: int = 3600):
        """Wait for a deployed job to complete using deployment ID"""
        import asyncio
        from datetime import datetime
        
        start_time = datetime.now()
        
        # First, get the actual job name from the deployment
        try:
            deployments_collection = get_deployments_collection()
            deployment_doc = await deployments_collection.find_one({"deployment_id": job_deployment_id})
            
            if not deployment_doc:
                raise Exception(f"Deployment {job_deployment_id} not found in database")
                
            job_name = deployment_doc.get("resource_name")
            if not job_name:
                raise Exception(f"Resource name not found for deployment {job_deployment_id}")
                
            logger.info(f"Waiting for job {job_name} (deployment: {job_deployment_id}) to complete")
            
            # Now wait for the job to complete
            await self._wait_for_benchmark_job_completion(
                job_name=job_name,
                namespace=namespace,
                timeout=timeout
            )
            
        except Exception as e:
            logger.error(f"Failed to wait for job completion (deployment: {job_deployment_id}): {e}")
            raise

    async def _wait_for_vllm_ready(self, release_name: str, namespace: str, timeout: int = 600):
        """Wait for VLLM service to be ready"""
        import asyncio
        import aiohttp
        from datetime import datetime
        
        start_time = datetime.now()
        logger.info(f"Waiting for VLLM service {release_name} in namespace {namespace} to be ready...")
        
        try:
            # First, wait for pods to be running
            await self._wait_for_pods_running(release_name, namespace, timeout // 2)
            
            # Then, check if VLLM API is responding
            service_url = f"http://{release_name}.{namespace}.svc.cluster.local:8000"
            health_endpoint = f"{service_url}/health"
            
            logger.info(f"Checking VLLM API health at {health_endpoint}")
            
            while True:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(health_endpoint, timeout=10) as response:
                            if response.status == 200:
                                logger.info(f"VLLM service {release_name} is ready and responding")
                                return
                            else:
                                logger.debug(f"VLLM health check returned status {response.status}")
                
                except Exception as e:
                    logger.debug(f"VLLM health check failed: {e}")
                
                # Check timeout
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed > timeout:
                    error_msg = f"Timeout waiting for VLLM service {release_name} to be ready (timeout: {timeout}s)"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                
                # Wait before next check
                await asyncio.sleep(15)  # Check every 15 seconds
                
        except Exception as e:
            # Check if this is a queue-based deployment and terminate it
            error_msg = f"VLLM readiness check failed for {release_name}: {str(e)}"
            logger.error(error_msg)
            
            # Try to get queue request ID from release annotations/labels
            queue_request_id = await self._get_queue_request_id_from_release(release_name, namespace)
            if queue_request_id:
                logger.info(f"Terminating queue request {queue_request_id} due to VLLM deployment failure")
                await self._terminate_queue_request(queue_request_id, error_msg)
            
            raise Exception(error_msg)

    async def _wait_for_pods_running(self, release_name: str, namespace: str, timeout: int = 600):
        """Wait for pods to be in running state"""
        import subprocess
        import asyncio
        import json
        from datetime import datetime
        
        start_time = datetime.now()
        logger.info(f"Waiting for pods of release {release_name} to be running...")
        
        while True:
            try:
                # Get pods for the release
                cmd = [
                    "kubectl", "get", "pods", 
                    "-l", f"app.kubernetes.io/instance={release_name}",
                    "-n", namespace,
                    "-o", "json"
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    try:
                        pods_data = json.loads(result.stdout)
                        pods = pods_data.get("items", [])
                        
                        if not pods:
                            logger.debug(f"No pods found for release {release_name}")
                        else:
                            all_running = True
                            failed_pods = []
                            
                            for pod in pods:
                                pod_name = pod['metadata']['name']
                                pod_status = pod.get('status', {}).get('phase', 'Unknown')
                                
                                logger.debug(f"Pod {pod_name} status: {pod_status}")
                                
                                # Check for failed states
                                if pod_status in ['Failed', 'Error']:
                                    failed_pods.append(f"{pod_name}: {pod_status}")
                                    all_running = False
                                elif pod_status != 'Running':
                                    # Check container statuses for more detailed error info
                                    container_statuses = pod.get('status', {}).get('containerStatuses', [])
                                    for container_status in container_statuses:
                                        waiting_state = container_status.get('state', {}).get('waiting', {})
                                        if waiting_state:
                                            reason = waiting_state.get('reason', '')
                                            message = waiting_state.get('message', '')
                                            if reason in ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError', 'CrashLoopBackOff']:
                                                failed_pods.append(f"{pod_name}: {reason} - {message}")
                                    
                                    all_running = False
                            
                            # If we have failed pods, raise an exception immediately
                            if failed_pods:
                                error_msg = f"Pods failed for release {release_name}: {'; '.join(failed_pods)}"
                                logger.error(error_msg)
                                
                                # Try to get queue request ID and update status
                                queue_request_id = await self._get_queue_request_id_from_release(release_name, namespace)
                                if queue_request_id:
                                    logger.info(f"Marking queue request {queue_request_id} as failed due to pod errors")
                                    await self._mark_request_failed(queue_request_id, error_msg)
                                
                                raise Exception(error_msg)
                            
                            if all_running:
                                logger.info(f"All pods for release {release_name} are running")
                                return
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse kubectl output: {e}")
                else:
                    logger.debug(f"Failed to get pods: {result.stderr}")
            
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse kubectl output: {e}")
            except Exception as e:
                # If it's our custom exception, re-raise it
                if "Pods failed for release" in str(e):
                    raise
                logger.debug(f"Error checking pod status: {e}")
            
            # Check timeout
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                error_msg = f"Timeout waiting for pods of release {release_name} to be running (timeout: {timeout}s)"
                logger.error(error_msg)
                
                # Try to get queue request ID and update status for timeout
                queue_request_id = await self._get_queue_request_id_from_release(release_name, namespace)
                if queue_request_id:
                    logger.info(f"Marking queue request {queue_request_id} as failed due to timeout")
                    await self._mark_request_failed(queue_request_id, error_msg)
                
                raise Exception(error_msg)
            
            # Wait before next check
            await asyncio.sleep(10)  # Check every 10 seconds

    async def _get_queue_request_id_from_release(self, release_name: str, namespace: str) -> Optional[str]:
        """Get queue request ID from Helm release annotations or labels"""
        try:
            import subprocess
            import asyncio
            import json
            
            # Try to get release info from Helm
            get_release_cmd = [
                "helm", "get", "values", release_name, 
                "-n", namespace, 
                "-o", "json"
            ]
            
            result = await asyncio.create_subprocess_exec(
                *get_release_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                try:
                    values_data = json.loads(stdout.decode())
                    # Check if queue_request_id is stored in values
                    queue_request_id = values_data.get('queue_request_id')
                    if queue_request_id:
                        return queue_request_id
                except json.JSONDecodeError:
                    pass
            
            # Fallback: try to find queue request by matching release name pattern
            # Release names are typically created with timestamp, so we can try to match
            queue_collection = await self._get_vllm_queue_collection()
            async for queue_doc in queue_collection.find({"status": {"$in": ["processing", "pending"]}}):
                # Check if this queue request might be related to this release
                vllm_config = queue_doc.get("vllm_config", {})
                model_name = vllm_config.get("model_name", "")
                if model_name:
                    clean_model_name = model_name.replace('/', '-').replace('_', '-').lower()
                    if clean_model_name in release_name:
                        return queue_doc["queue_request_id"]
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to get queue request ID from release {release_name}: {e}")
            return None

    async def _terminate_queue_request(self, queue_request_id: str, error_message: str):
        """Terminate a queue request due to deployment failure"""
        try:
            queue_collection = await self._get_vllm_queue_collection()
            
            # Update the queue request status to failed
            update_result = await queue_collection.update_one(
                {"queue_request_id": queue_request_id},
                {
                    "$set": {
                        "status": "failed",
                        "error_message": error_message,
                        "completed_at": datetime.now()
                    }
                }
            )
            
            if update_result.modified_count > 0:
                logger.info(f"Successfully terminated queue request {queue_request_id}")
                
                # Also update the benchmark-vllm queue if this was a Helm deployment
                await self._update_queue_status(queue_request_id, "failed", None, error_message)
            else:
                logger.warning(f"Queue request {queue_request_id} not found or already processed")
                
        except Exception as e:
            logger.error(f"Failed to terminate queue request {queue_request_id}: {e}")

    async def _get_vllm_queue_collection(self):
        """Get VLLM queue collection"""
        from database import get_database
        db = get_database()
        return db.vllm_deployment_queue

    async def start_queue_monitoring(self):
        """Start background queue monitoring for pod status"""
        if hasattr(self, 'monitoring_task') and self.monitoring_task and not self.monitoring_task.done():
            logger.info("Queue monitoring already running")
            return
            
        logger.info("Starting queue monitoring...")
        self.monitoring_task = asyncio.create_task(self._queue_monitoring_loop())

    async def stop_queue_monitoring(self):
        """Stop background queue monitoring"""
        if hasattr(self, 'monitoring_task') and self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            logger.info("Queue monitoring stopped")

    async def _queue_monitoring_loop(self):
        """Background loop to monitor processing queue requests"""
        while True:
            try:
                await self._monitor_processing_requests()
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue monitoring loop: {e}")
                await asyncio.sleep(30)

    async def _monitor_processing_requests(self):
        """Monitor processing queue requests for pod failures"""
        try:
            queue_collection = await self._get_vllm_queue_collection()
            
            # Find all processing requests
            processing_requests = []
            async for request in queue_collection.find({"status": "processing"}):
                processing_requests.append(request)
            
            for request in processing_requests:
                queue_request_id = request["queue_request_id"]
                current_step = request.get("current_step", "")
                
                # Check VLLM deployment status if in vllm_deployment step
                if current_step == "vllm_deployment" and request.get("vllm_deployment_id"):
                    deployment_id = request["vllm_deployment_id"]
                    if deployment_id != "existing-vllm":  # Skip existing VLLM check
                        await self._check_vllm_deployment_status(queue_request_id, deployment_id)
                
                # Check benchmark job status if in benchmark steps
                elif current_step.startswith("benchmark_job_"):
                    await self._check_benchmark_job_status(queue_request_id, request)
                    
        except Exception as e:
            logger.error(f"Error monitoring processing requests: {e}")

    async def _check_vllm_deployment_status(self, queue_request_id: str, deployment_id: str):
        """Check VLLM deployment status and update queue if failed"""
        try:
            # Check deployment status from VLLM manager
            import aiohttp
            from config import BENCHMARK_VLLM_URL
            
            async with aiohttp.ClientSession() as session:
                url = f"{BENCHMARK_VLLM_URL}/deployments/{deployment_id}/status"
                async with session.get(url) as response:
                    if response.status == 200:
                        deployment_info = await response.json()
                        
                        if deployment_info.get("status") == "failed":
                            error_message = deployment_info.get("error_message", "VLLM deployment failed")
                            logger.warning(f"VLLM deployment {deployment_id} failed, updating queue request {queue_request_id}")
                            await self._mark_request_failed(queue_request_id, f"VLLM deployment failed: {error_message}")
                            
        except Exception as e:
            logger.debug(f"Error checking VLLM deployment status: {e}")

    async def _check_benchmark_job_status(self, queue_request_id: str, request: dict):
        """Check benchmark job status and update queue if failed"""
        try:
            benchmark_job_ids = request.get("benchmark_job_ids", [])
            
            for job_id in benchmark_job_ids:
                # Check job status
                try:
                    job_status = await k8s_client.get_job_status(job_id, request.get("namespace", "default"))
                    
                    if job_status.status.value == "failed":
                        error_message = f"Benchmark job {job_id} failed"
                        logger.warning(f"Benchmark job {job_id} failed, updating queue request {queue_request_id}")
                        await self._mark_request_failed(queue_request_id, error_message)
                        return
                        
                except Exception as job_error:
                    logger.debug(f"Error checking job {job_id}: {job_error}")
                    
        except Exception as e:
            logger.debug(f"Error checking benchmark job status: {e}")

    async def delete_job(self, job_name: str, namespace: str) -> bool:
        """Delete a job by name"""
        try:
            logger.info(f"Deleting job '{job_name}' in namespace '{namespace}'")
            
            # Use Kubernetes client to delete the job
            success = await k8s_client.delete_job(job_name, namespace)
            
            if success:
                # Update deployment status in database
                deployments_collection = get_deployments_collection()
                result = await deployments_collection.update_many(
                    {
                        "resource_name": job_name,
                        "namespace": namespace,
                        "resource_type": {"$in": ["job", "Job"]},
                        "status": {"$ne": "deleted"}
                    },
                    {"$set": {"status": "deleted", "deleted_at": datetime.now()}}
                )
                
                if result.modified_count > 0:
                    logger.info(f"Updated database status for deleted job {job_name} ({result.modified_count} records)")
                
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"Error deleting job {job_name}: {e}")
            raise Exception(f"Failed to delete job: {str(e)}")

    async def cancel_vllm_queue_request(self, queue_request_id: str) -> bool:
        """Cancel a VLLM queue request and clean up resources"""
        try:
            logger.info(f"Attempting to cancel VLLM queue request {queue_request_id}")
            
            # Get queue collection
            queue_collection = await self._get_vllm_queue_collection()
            
            # Find the queue request
            queue_request = await queue_collection.find_one({"queue_request_id": queue_request_id})
            if not queue_request:
                logger.warning(f"Queue request {queue_request_id} not found")
                return False
            
            # Only allow cancellation of pending or processing requests
            if queue_request.get("status") not in ["pending", "processing"]:
                logger.warning(f"Cannot cancel queue request {queue_request_id} with status {queue_request.get('status')}")
                return False
            
            logger.info(f"Cancelling queue request {queue_request_id} with status {queue_request.get('status')}")
            
            # Clean up resources if processing
            if queue_request.get("status") == "processing":
                await self._cleanup_processing_vllm_request(queue_request_id, queue_request)
            
            # Update status to cancelled
            await queue_collection.update_one(
                {"queue_request_id": queue_request_id},
                {
                    "$set": {
                        "status": "cancelled",
                        "completed_at": datetime.now(),
                        "error_message": "Cancelled by user"
                    }
                }
            )
            
            logger.info(f"Successfully cancelled VLLM queue request {queue_request_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling VLLM queue request {queue_request_id}: {e}")
            return False

    async def _cleanup_processing_vllm_request(self, queue_request_id: str, queue_request: dict):
        """Clean up resources for a processing VLLM request"""
        try:
            logger.info(f"Cleaning up processing VLLM request {queue_request_id}")
            
            # 1. Clean up benchmark jobs
            benchmark_job_ids = queue_request.get("benchmark_job_ids", [])
            if benchmark_job_ids:
                logger.info(f"Cleaning up {len(benchmark_job_ids)} benchmark jobs")
                for job_id in benchmark_job_ids:
                    try:
                        # Try to get job name from deployments collection
                        deployments_collection = get_deployments_collection()
                        deployment_doc = await deployments_collection.find_one({"deployment_id": job_id})
                        
                        if deployment_doc:
                            job_name = deployment_doc.get("resource_name")
                            namespace = deployment_doc.get("namespace", "default")
                            
                            if job_name:
                                logger.info(f"Deleting benchmark job {job_name} in namespace {namespace}")
                                await self.delete_job(job_name, namespace)
                        
                    except Exception as e:
                        logger.warning(f"Error cleaning up benchmark job {job_id}: {e}")
                        continue
            
            # 2. Clean up VLLM deployment if it was created by this request
            vllm_deployment_id = queue_request.get("vllm_deployment_id")
            if vllm_deployment_id and vllm_deployment_id != "existing-vllm":
                logger.info(f"Cleaning up VLLM deployment {vllm_deployment_id}")
                
                # Check if other requests are using this deployment
                other_requests = await self._get_vllm_queue_collection().find({
                    "vllm_deployment_id": vllm_deployment_id,
                    "queue_request_id": {"$ne": queue_request_id},
                    "status": {"$in": ["pending", "processing"]}
                }).to_list(length=None)
                
                if not other_requests:
                    # No other requests using this deployment, safe to delete
                    try:
                        # Call VLLM service to stop deployment
                        import aiohttp
                        from config import BENCHMARK_VLLM_URL
                        
                        async with aiohttp.ClientSession() as session:
                            delete_url = f"{BENCHMARK_VLLM_URL}/deployments/{vllm_deployment_id}"
                            async with session.delete(delete_url) as response:
                                if response.status in [200, 204, 404]:
                                    logger.info(f"Successfully deleted VLLM deployment {vllm_deployment_id}")
                                else:
                                    error_text = await response.text()
                                    logger.warning(f"Failed to delete VLLM deployment: HTTP {response.status} - {error_text}")
                    
                    except Exception as e:
                        logger.warning(f"Error deleting VLLM deployment {vllm_deployment_id}: {e}")
                else:
                    logger.info(f"VLLM deployment {vllm_deployment_id} is used by {len(other_requests)} other requests, not deleting")
            
            logger.info(f"Completed cleanup for VLLM request {queue_request_id}")
            
        except Exception as e:
            logger.error(f"Error during cleanup of VLLM request {queue_request_id}: {e}")

# Global instance
deployer_manager = DeployerManager() 
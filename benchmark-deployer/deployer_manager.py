import logging
import yaml
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid

# Import our modules
from config import DEFAULT_NAMESPACE, LOG_LEVEL
from models import (
    DeploymentRequest, DeploymentResponse, LogRequest, LogResponse,
    DeleteRequest, DeleteResponse, JobStatusResponse, ResourceType,
    TerminalSessionRequest, TerminalSessionResponse, TerminalSessionInfo, TerminalSessionListResponse
)
from kubernetes_client import k8s_client
from terminal_manager import terminal_manager
from database import connect_to_mongo, get_deployments_collection

# Configure logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)

class DeployerManager:
    def __init__(self):
        pass

    async def initialize(self):
        """Initialize the deployer manager."""
        try:
            # Initialize MongoDB connection
            await connect_to_mongo()
            logger.info("MongoDB connection initialized")
            
            # Initialize Kubernetes client
            await k8s_client.initialize()
            logger.info("Deployer manager initialized with Kubernetes connection")
        except Exception as e:
            logger.warning(f"Failed to initialize Kubernetes client: {e}. Running without Kubernetes connection.")
            logger.info("Deployer manager initialized without Kubernetes connection")

    async def deploy_yaml(self, request: DeploymentRequest) -> DeploymentResponse:
        """Deploy YAML content to Kubernetes."""
        try:
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
            # Safely get Kubernetes version
            kubernetes_version = None
            if k8s_client.is_connected:
                try:
                    kubernetes_version = await k8s_client.get_kubernetes_version()
                except Exception as e:
                    logger.debug(f"Could not get Kubernetes version: {e}")
            
            # Get active deployments count from database
            active_deployments_count = 0
            try:
                deployments_collection = get_deployments_collection()
                active_deployments_count = await deployments_collection.count_documents({"status": {"$ne": "deleted"}})
            except Exception as e:
                logger.debug(f"Could not get active deployments count: {e}")
            
            return {
                "kubernetes_connected": k8s_client.is_connected,
                "kubernetes_version": kubernetes_version,
                "active_deployments": active_deployments_count,
                "service_status": "healthy" if k8s_client.is_connected else "degraded"
            }
            
        except Exception as e:
            logger.error(f"Failed to get system health: {e}")
            return {
                "kubernetes_connected": False,
                "kubernetes_version": None,
                "active_deployments": 0,
                "service_status": "unhealthy",
                "error": str(e)
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

# Create global instance
deployer_manager = DeployerManager() 
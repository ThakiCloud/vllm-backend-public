import asyncio
import logging
import yaml
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from bson import ObjectId
from models import VLLMConfig, VLLMDeploymentResponse
from database import get_database
from kubernetes_client import kubernetes_client
from vllm_templates import create_vllm_deployment_template, create_vllm_statefulset_template, create_vllm_service_template, create_vllm_headless_service_template, _sanitize_k8s_name
from config import VLLM_NAMESPACE
import uuid

logger = logging.getLogger(__name__)

def _clean_mongo_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Clean MongoDB data by converting ObjectId to string and removing _id field"""
    if isinstance(data, dict):
        cleaned_data = {}
        for key, value in data.items():
            if key == '_id':
                continue  # Skip MongoDB _id field
            elif isinstance(value, ObjectId):
                cleaned_data[key] = str(value)
            elif isinstance(value, dict):
                cleaned_data[key] = _clean_mongo_data(value)
            elif isinstance(value, list):
                cleaned_data[key] = [_clean_mongo_data(item) if isinstance(item, dict) else item for item in value]
            else:
                cleaned_data[key] = value
        return cleaned_data
    return data

class VLLMManager:
    def __init__(self):
        self.deployments: Dict[str, Dict[str, Any]] = {}
        self.kubernetes_deployments: Dict[str, str] = {}  # deployment_id -> k8s_deployment_name
        self.initialized = False
    
    async def initialize(self):
        """Initialize the vLLM manager"""
        if not self.initialized:
            await kubernetes_client.initialize()
            
            # Sync existing Kubernetes resources
            await self._sync_existing_resources()
            
            self.initialized = True
            logger.info("VLLMManager initialized successfully")

    async def load_config_from_yaml(self, config_file: str) -> VLLMConfig:
        """Load vLLM configuration from YAML file"""
        try:
            if not os.path.exists(config_file):
                raise FileNotFoundError(f"Configuration file not found: {config_file}")
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            logger.info(f"Loaded configuration from {config_file}")
            return VLLMConfig(**config_data)
            
        except Exception as e:
            logger.error(f"Failed to load configuration from {config_file}: {e}")
            raise

    async def deploy_vllm(self, config: VLLMConfig, deployment_name: Optional[str] = None) -> VLLMDeploymentResponse:
        """Deploy vLLM server to Kubernetes"""
        try:
            if not self.initialized:
                await self.initialize()
            
            # Sync with Kubernetes to ensure we have latest state
            await self._sync_existing_resources()
            
            # Check for existing deployments with same configuration
            existing_deployment = await self._find_matching_deployment(config)
            if existing_deployment:
                logger.info(f"Found existing deployment with matching configuration: {existing_deployment['deployment_id']}")
                
                # Verify the deployment is actually running in Kubernetes
                k8s_status = await self._verify_kubernetes_deployment(existing_deployment)
                if k8s_status:
                    logger.info(f"Verified deployment {existing_deployment['deployment_id']} is running in Kubernetes")
                    # Update status if needed
                    existing_deployment["status"] = k8s_status
                    await self._update_deployment_in_db(existing_deployment["deployment_id"], existing_deployment)
                    
                    return VLLMDeploymentResponse( 
                        deployment_id=existing_deployment["deployment_id"],
                        deployment_name=existing_deployment["deployment_name"],
                        status=existing_deployment["status"],
                        config=VLLMConfig(**existing_deployment["config"]),
                        created_at=existing_deployment["created_at"],
                        message="Reusing existing deployment with matching configuration"
                    )
                else:
                    logger.warning(f"Deployment {existing_deployment['deployment_id']} not found in Kubernetes, removing from cache")
                    # Remove from cache if not found in Kubernetes
                    if existing_deployment["deployment_id"] in self.deployments:
                        del self.deployments[existing_deployment["deployment_id"]]
                    # Continue to create new deployment
            
            # Check for GPU resource conflicts
            conflicting_deployments = await self._find_conflicting_deployments(config)
            if conflicting_deployments:
                logger.info(f"Found {len(conflicting_deployments)} conflicting deployments, stopping them...")
                for conflicting_deployment in conflicting_deployments:
                    await self.stop_deployment(conflicting_deployment["deployment_id"])
                    logger.info(f"Stopped conflicting deployment: {conflicting_deployment['deployment_id']}")
            
            deployment_id = str(uuid.uuid4())
            if not deployment_name:
                # Clean model name for Kubernetes naming using proper sanitization
                clean_model_name = _sanitize_k8s_name(config.model_name)
                # Use fixed deployment name based on model name and config for consistent pod naming
                # Include key config parameters to ensure uniqueness when needed
                config_hash = f"{config.tensor_parallel_size}-{config.gpu_resource_type}-{config.gpu_resource_count}"
                deployment_name = f"vllm-{clean_model_name}-{config_hash}"
                # Ensure the full deployment name is also sanitized
                deployment_name = _sanitize_k8s_name(deployment_name)
            
            service_name = _sanitize_k8s_name(f"{deployment_name}-service")
            headless_service_name = _sanitize_k8s_name(f"{deployment_name}-headless")
            
            logger.info(f"Starting vLLM Kubernetes StatefulSet: {deployment_name}")
            logger.info(f"Model: {config.model_name}")
            logger.info(f"GPU Resource: {config.gpu_resource_type} x {config.gpu_resource_count}")
            logger.info(f"Pod will be named: {deployment_name}-0")
            
            # Create Kubernetes StatefulSet manifest
            statefulset_manifest = create_vllm_statefulset_template(
                deployment_name=deployment_name,
                config=config,
                deployment_id=deployment_id,
                namespace=VLLM_NAMESPACE
            )
            
            # Create Kubernetes headless service manifest (required for StatefulSet)
            headless_service_manifest = create_vllm_headless_service_template(
                service_name=headless_service_name,
                deployment_id=deployment_id,
                port=config.port,
                namespace=VLLM_NAMESPACE
            )
            
            # Create Kubernetes regular service manifest (for external access)
            service_manifest = create_vllm_service_template(
                service_name=service_name,
                deployment_id=deployment_id,
                port=config.port,
                namespace=VLLM_NAMESPACE
            )
            
            # Deploy to Kubernetes
            k8s_statefulset_name = await kubernetes_client.create_statefulset(statefulset_manifest)
            k8s_headless_service_name = await kubernetes_client.create_service(headless_service_manifest)
            k8s_service_name = await kubernetes_client.create_service(service_manifest)
            
            # Store deployment info
            deployment_info = {
                "deployment_id": deployment_id,
                "deployment_name": deployment_name,
                "k8s_statefulset_name": k8s_statefulset_name,
                "k8s_headless_service_name": k8s_headless_service_name,
                "k8s_service_name": k8s_service_name,
                "pod_name": f"{deployment_name}-0",  # StatefulSet pod name is predictable
                "config": config.dict(),
                "status": "starting",
                "created_at": datetime.utcnow(),
                "namespace": VLLM_NAMESPACE
            }
            
            self.deployments[deployment_id] = deployment_info
            self.kubernetes_deployments[deployment_id] = k8s_statefulset_name
            
            # Save to database
            await self._save_deployment_to_db(deployment_info)
            
            # Start monitoring task
            asyncio.create_task(self._monitor_deployment(deployment_id))
            
            return VLLMDeploymentResponse(
                deployment_id=deployment_id,
                deployment_name=deployment_name,
                status="starting",
                config=config,
                created_at=deployment_info["created_at"],
                message="vLLM Kubernetes deployment started successfully"
            )
            
        except Exception as e:
            logger.error(f"Failed to deploy vLLM to Kubernetes: {e}")
            raise

    async def _find_matching_deployment(self, config: VLLMConfig) -> Optional[Dict[str, Any]]:
        """Find existing deployment with matching configuration"""
        try:
            logger.info(f"Looking for existing deployment with matching config for model: {config.model_name}")
            logger.info(f"Target config: gpu_type={config.gpu_resource_type}, gpu_count={config.gpu_resource_count}, "
                       f"tensor_parallel={config.tensor_parallel_size}, dtype={config.dtype}")
            
            # Check in-memory deployments first
            logger.info(f"Checking {len(self.deployments)} in-memory deployments...")
            for deployment_id, deployment_info in self.deployments.items():
                logger.info(f"Checking deployment {deployment_id}: status={deployment_info['status']}")
                if deployment_info["status"] in ["running", "starting"]:
                    existing_config = VLLMConfig(**deployment_info["config"])
                    logger.info(f"Existing config: model={existing_config.model_name}, "
                               f"gpu_type={existing_config.gpu_resource_type}, "
                               f"gpu_count={existing_config.gpu_resource_count}, "
                               f"tensor_parallel={existing_config.tensor_parallel_size}, "
                               f"dtype={existing_config.dtype}")
                    
                    if config.matches_config(existing_config):
                        logger.info(f"Found matching deployment in memory: {deployment_id}")
                        return deployment_info
                    else:
                        logger.info(f"Config does not match for deployment {deployment_id}")
            
            # Check database for deployments not in memory
            logger.info("Checking database for additional deployments...")
            db = get_database()
            collection = db.vllm_deployments
            async for deployment_doc in collection.find({"status": {"$in": ["running", "starting"]}}):
                deployment_id = deployment_doc["deployment_id"]
                if deployment_id not in self.deployments:
                    logger.info(f"Found deployment {deployment_id} in database but not in memory")
                    existing_config = VLLMConfig(**deployment_doc["config"])
                    if config.matches_config(existing_config):
                        logger.info(f"Found matching deployment in database: {deployment_id}")
                        # Add to memory cache
                        cleaned_doc = _clean_mongo_data(deployment_doc)
                        self.deployments[deployment_id] = cleaned_doc
                        return cleaned_doc
            
            logger.info("No matching deployment found")
            return None
        except Exception as e:
            logger.error(f"Error finding matching deployment: {e}")
            return None

    async def _verify_kubernetes_deployment(self, deployment_info: Dict[str, Any]) -> Optional[str]:
        """Verify that a deployment is actually running in Kubernetes and return its status"""
        try:
            deployment_id = deployment_info["deployment_id"]
            
            # Check if it's a StatefulSet or Deployment
            k8s_statefulset_name = deployment_info.get("k8s_statefulset_name")
            k8s_deployment_name = deployment_info.get("k8s_deployment_name")
            pod_name = deployment_info.get("pod_name")
            
            if k8s_statefulset_name:
                # Check StatefulSet
                statefulset = await kubernetes_client.get_statefulset(k8s_statefulset_name)
                if not statefulset:
                    logger.warning(f"StatefulSet {k8s_statefulset_name} not found in Kubernetes")
                    return None
                
                # Check if pod is ready
                if pod_name:
                    pod_status = await kubernetes_client.get_pod_status(pod_name)
                    if pod_status and pod_status.get("ready"):
                        return "running"
                    elif pod_status:
                        return "starting"
                    else:
                        return None
                        
            elif k8s_deployment_name:
                # Check legacy Deployment
                deployment = await kubernetes_client.get_deployment(k8s_deployment_name)
                if not deployment:
                    logger.warning(f"Deployment {k8s_deployment_name} not found in Kubernetes")
                    return None
                
                # Check deployment status
                if deployment.get("ready_replicas", 0) > 0:
                    return "running"
                else:
                    return "starting"
            
            return None
            
        except Exception as e:
            logger.error(f"Error verifying Kubernetes deployment {deployment_info.get('deployment_id')}: {e}")
            return None

    async def _find_conflicting_deployments(self, config: VLLMConfig) -> List[Dict[str, Any]]:
        """Find deployments that conflict with the given configuration's GPU resources"""
        try:
            conflicting_deployments = []
            
            # Check in-memory deployments first
            for deployment_id, deployment_info in self.deployments.items():
                if deployment_info["status"] in ["running", "starting"]:
                    existing_config = VLLMConfig(**deployment_info["config"])
                    if config.conflicts_with_gpu_resources(existing_config):
                        conflicting_deployments.append(deployment_info)
            
            # Check database for deployments not in memory
            db = get_database()
            collection = db.vllm_deployments
            async for deployment_doc in collection.find({"status": {"$in": ["running", "starting"]}}):
                if deployment_doc["deployment_id"] not in self.deployments:
                    existing_config = VLLMConfig(**deployment_doc["config"])
                    if config.conflicts_with_gpu_resources(existing_config):
                        # Add to memory cache
                        cleaned_doc = _clean_mongo_data(deployment_doc)
                        self.deployments[deployment_doc["deployment_id"]] = cleaned_doc
                        conflicting_deployments.append(cleaned_doc)
            
            return conflicting_deployments
        except Exception as e:
            logger.error(f"Error finding conflicting deployments: {e}")
            return []

    async def _monitor_deployment(self, deployment_id: str):
        """Monitor Kubernetes StatefulSet status"""
        try:
            deployment_info = self.deployments.get(deployment_id)
            if not deployment_info:
                return
            
            k8s_statefulset_name = deployment_info.get("k8s_statefulset_name")
            if not k8s_statefulset_name:
                # Fallback to old deployment monitoring for backward compatibility
                k8s_deployment_name = deployment_info.get("k8s_deployment_name")
                if k8s_deployment_name:
                    await self._monitor_legacy_deployment(deployment_id, k8s_deployment_name)
                return
            
            # Wait a bit for the StatefulSet to start
            await asyncio.sleep(10)
            
            # Check StatefulSet status
            for attempt in range(30):  # Monitor for up to 5 minutes
                status = await kubernetes_client.get_statefulset_status(k8s_statefulset_name)
                
                if status:
                    ready_replicas = status.get("ready_replicas", 0)
                    current_replicas = status.get("current_replicas", 0)
                    
                    if ready_replicas > 0 and current_replicas > 0:
                        deployment_info["status"] = "running"
                        logger.info(f"StatefulSet {deployment_id} is running (pod: {deployment_info.get('pod_name')})")
                        break
                    elif any(
                        condition.get("type") == "Progressing" and 
                        condition.get("status") == "False" and 
                        condition.get("reason") == "ProgressDeadlineExceeded"
                        for condition in status.get("conditions", [])
                    ):
                        deployment_info["status"] = "failed"
                        deployment_info["error_message"] = "StatefulSet progress deadline exceeded"
                        logger.error(f"StatefulSet {deployment_id} failed: Progress deadline exceeded")
                        
                        # Update related queue request if exists
                        await self._update_related_queue_request(deployment_id, "failed", "StatefulSet progress deadline exceeded")
                        break
                else:
                    deployment_info["status"] = "failed"
                    deployment_info["error_message"] = "StatefulSet not found"
                    logger.error(f"StatefulSet {deployment_id} failed: StatefulSet not found")
                    
                    # Update related queue request if exists
                    await self._update_related_queue_request(deployment_id, "failed", "StatefulSet not found")
                    break
                
                # Check pod states for more detailed error detection
                pod_error = await self._check_pod_errors(k8s_statefulset_name, deployment_info.get("namespace", "default"))
                if pod_error:
                    deployment_info["status"] = "failed"
                    deployment_info["error_message"] = pod_error
                    logger.error(f"StatefulSet {deployment_id} failed: {pod_error}")
                    
                    # Update related queue request if exists
                    await self._update_related_queue_request(deployment_id, "failed", pod_error)
                    break
                
                await asyncio.sleep(10)  # Wait 10 seconds before next check
            
            # Update database
            await self._update_deployment_in_db(deployment_id, deployment_info)
            
        except Exception as e:
            logger.error(f"Error monitoring StatefulSet {deployment_id}: {e}")
            
            # Mark deployment as failed and update queue request
            deployment_info = self.deployments.get(deployment_id, {})
            deployment_info["status"] = "failed"
            deployment_info["error_message"] = str(e)
            await self._update_deployment_in_db(deployment_id, deployment_info)
            await self._update_related_queue_request(deployment_id, "failed", str(e))

    async def _monitor_legacy_deployment(self, deployment_id: str, k8s_deployment_name: str):
        """Monitor legacy Kubernetes deployment status for backward compatibility"""
        try:
            deployment_info = self.deployments.get(deployment_id)
            if not deployment_info:
                return
            
            # Check deployment status
            for attempt in range(30):  # Monitor for up to 5 minutes
                status = await kubernetes_client.get_deployment_status(k8s_deployment_name)
                
                if status:
                    ready_replicas = status.get("ready_replicas", 0)
                    available_replicas = status.get("available_replicas", 0)
                    
                    if ready_replicas > 0 and available_replicas > 0:
                        deployment_info["status"] = "running"
                        logger.info(f"Deployment {deployment_id} is running")
                        break
                    elif any(
                        condition.get("type") == "Progressing" and 
                        condition.get("status") == "False" and 
                        condition.get("reason") == "ProgressDeadlineExceeded"
                        for condition in status.get("conditions", [])
                    ):
                        deployment_info["status"] = "failed"
                        deployment_info["error_message"] = "Deployment progress deadline exceeded"
                        logger.error(f"Deployment {deployment_id} failed: Progress deadline exceeded")
                        break
                else:
                    deployment_info["status"] = "failed"
                    deployment_info["error_message"] = "Deployment not found"
                    logger.error(f"Deployment {deployment_id} failed: Deployment not found")
                    break
                
                await asyncio.sleep(10)  # Wait 10 seconds before next check
            
            # Update database
            await self._update_deployment_in_db(deployment_id, deployment_info)
            
        except Exception as e:
            logger.error(f"Error monitoring legacy deployment {deployment_id}: {e}")

    async def stop_deployment(self, deployment_id: str) -> bool:
        """Stop vLLM Kubernetes deployment or StatefulSet"""
        try:
            deployment_info = self.deployments.get(deployment_id)
            
            if not deployment_info:
                return False
            
            # Check if it's a StatefulSet or legacy Deployment
            k8s_statefulset_name = deployment_info.get("k8s_statefulset_name")
            k8s_deployment_name = deployment_info.get("k8s_deployment_name")
            k8s_service_name = deployment_info.get("k8s_service_name")
            k8s_headless_service_name = deployment_info.get("k8s_headless_service_name")
            
            resource_deleted = False
            
            if k8s_statefulset_name:
                # Delete StatefulSet
                resource_deleted = await kubernetes_client.delete_statefulset(k8s_statefulset_name)
                
                # Delete headless service
                if k8s_headless_service_name:
                    await kubernetes_client.delete_service(k8s_headless_service_name)
                    
                logger.info(f"Stopped StatefulSet {deployment_id} (pod was: {deployment_info.get('pod_name')})")
                
            elif k8s_deployment_name:
                # Delete legacy Deployment
                resource_deleted = await kubernetes_client.delete_deployment(k8s_deployment_name)
                logger.info(f"Stopped legacy Deployment {deployment_id}")
            else:
                return False
            
            # Delete regular service
            if k8s_service_name:
                await kubernetes_client.delete_service(k8s_service_name)
            
            # Update status
            deployment_info["status"] = "stopped"
            await self._update_deployment_in_db(deployment_id, deployment_info)
            
            # Clean up
            if deployment_id in self.kubernetes_deployments:
                del self.kubernetes_deployments[deployment_id]
            
            return resource_deleted
            
        except Exception as e:
            logger.error(f"Failed to stop deployment {deployment_id}: {e}")
            return False

    async def get_deployment_status(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """Get deployment status"""
        return self.deployments.get(deployment_id)

    async def list_deployments(self) -> Dict[str, Dict[str, Any]]:
        """List all deployments"""
        return _clean_mongo_data(self.deployments)

    async def _save_deployment_to_db(self, deployment_info: Dict[str, Any]):
        """Save deployment info to database"""
        try:
            db = get_database()
            collection = db.vllm_deployments
            await collection.insert_one(deployment_info)
        except Exception as e:
            logger.error(f"Failed to save deployment to database: {e}")

    async def _update_deployment_in_db(self, deployment_id: str, deployment_info: Dict[str, Any]):
        """Update deployment info in database"""
        try:
            db = get_database()
            collection = db.vllm_deployments
            await collection.update_one(
                {"deployment_id": deployment_id},
                {"$set": deployment_info}
            )
        except Exception as e:
            logger.error(f"Failed to update deployment in database: {e}")

    async def _sync_existing_resources(self):
        """Sync existing Kubernetes resources with manager state"""
        try:
            logger.info("Syncing existing Kubernetes resources...")
            
            # Load deployments from database first
            await self._load_deployments_from_db()
            
            # Get all StatefulSets in vllm namespace with app=vllm label
            statefulsets = await kubernetes_client.list_statefulsets_with_label("app=vllm")
            
            synced_count = 0
            for statefulset in statefulsets:
                statefulset_name = statefulset.get("name")
                deployment_id = statefulset.get("labels", {}).get("deployment-id")
                
                if not deployment_id:
                    logger.warning(f"StatefulSet {statefulset_name} has no deployment-id label")
                    continue
                
                # Check if we already have this deployment in memory
                if deployment_id not in self.deployments:
                    # Try to reconstruct deployment info from Kubernetes resource
                    deployment_info = await self._reconstruct_deployment_info(statefulset)
                    if deployment_info:
                        self.deployments[deployment_id] = deployment_info
                        self.kubernetes_deployments[deployment_id] = statefulset_name
                        synced_count += 1
                        logger.info(f"Synced existing StatefulSet: {statefulset_name} (deployment: {deployment_id})")
            
            logger.info(f"Successfully synced {synced_count} existing resources")
            
        except Exception as e:
            logger.error(f"Failed to sync existing resources: {e}")

    async def _load_deployments_from_db(self):
        """Load deployment info from database"""
        try:
            db = get_database()
            collection = db.vllm_deployments
            
            async for deployment_doc in collection.find():
                deployment_id = deployment_doc["deployment_id"]
                if deployment_id not in self.deployments:
                    # Clean and add to memory
                    cleaned_doc = _clean_mongo_data(deployment_doc)
                    self.deployments[deployment_id] = cleaned_doc
                    
                    # Add to kubernetes_deployments mapping if available
                    k8s_statefulset_name = deployment_doc.get("k8s_statefulset_name")
                    if k8s_statefulset_name:
                        self.kubernetes_deployments[deployment_id] = k8s_statefulset_name
                        
        except Exception as e:
            logger.error(f"Failed to load deployments from database: {e}")

    async def _reconstruct_deployment_info(self, statefulset: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Reconstruct deployment info from Kubernetes StatefulSet"""
        try:
            statefulset_name = statefulset.get("name")
            labels = statefulset.get("labels", {})
            deployment_id = labels.get("deployment-id")
            model = labels.get("model")
            
            if not deployment_id:
                return None
            
            # Get StatefulSet status to determine current state
            status = await kubernetes_client.get_statefulset_status(statefulset_name)
            if not status:
                return None
            
            # Determine deployment status
            ready_replicas = status.get("ready_replicas", 0)
            current_replicas = status.get("current_replicas", 0)
            
            if ready_replicas > 0 and current_replicas > 0:
                deployment_status = "running"
            else:
                deployment_status = "starting"
            
            # Reconstruct basic deployment info
            deployment_info = {
                "deployment_id": deployment_id,
                "deployment_name": statefulset_name,
                "k8s_statefulset_name": statefulset_name,
                "k8s_service_name": f"{statefulset_name}-service",
                "k8s_headless_service_name": f"{statefulset_name}-headless",
                "pod_name": f"{statefulset_name}-0",
                "status": deployment_status,
                "namespace": VLLM_NAMESPACE,
                "created_at": datetime.utcnow(),  # We don't have the original creation time
                "config": {
                    "model_name": model or "unknown",
                    "gpu_memory_utilization": 0.0,
                    "max_num_seqs": 2,
                    "block_size": 16,
                    "tensor_parallel_size": 1,
                    "pipeline_parallel_size": 1,
                    "trust_remote_code": False,
                    "dtype": "float32",
                    "port": 8000,
                    "host": "0.0.0.0",
                    "gpu_resource_type": "cpu",
                    "gpu_resource_count": 0,
                    "additional_args": {}
                }
            }
            
            return deployment_info
            
        except Exception as e:
            logger.error(f"Failed to reconstruct deployment info for StatefulSet {statefulset.get('name')}: {e}")
            return None

    async def _check_pod_errors(self, statefulset_name: str, namespace: str) -> str:
        """Check for pod errors in StatefulSet"""
        try:
            import subprocess
            import json
            
            # Get pods for the StatefulSet
            cmd = [
                "kubectl", "get", "pods", 
                "-l", f"app={statefulset_name}",
                "-n", namespace,
                "-o", "json"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                pods_data = json.loads(result.stdout)
                pods = pods_data.get("items", [])
                
                for pod in pods:
                    pod_name = pod['metadata']['name']
                    pod_status = pod.get('status', {}).get('phase', 'Unknown')
                    
                    # Check for failed states
                    if pod_status in ['Failed', 'Error']:
                        return f"Pod {pod_name} is in {pod_status} state"
                    
                    # Check container statuses for more detailed error info
                    container_statuses = pod.get('status', {}).get('containerStatuses', [])
                    for container_status in container_statuses:
                        waiting_state = container_status.get('state', {}).get('waiting', {})
                        if waiting_state:
                            reason = waiting_state.get('reason', '')
                            message = waiting_state.get('message', '')
                            if reason in ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError', 'CrashLoopBackOff']:
                                return f"Pod {pod_name}: {reason} - {message}"
            
            return None
            
        except Exception as e:
            logger.warning(f"Error checking pod errors: {e}")
            return None

    async def _update_related_queue_request(self, deployment_id: str, status: str, error_message: str):
        """Update related queue request status if exists"""
        try:
            from database import get_database
            
            # Find queue request with this deployment_id
            db = get_database()
            queue_collection = db.vllm_deployment_queue
            
            queue_request = await queue_collection.find_one({"vllm_deployment_id": deployment_id})
            if queue_request:
                queue_request_id = queue_request["queue_request_id"]
                logger.info(f"Updating queue request {queue_request_id} status to {status}")
                
                update_data = {
                    "status": status,
                    "completed_at": datetime.utcnow()
                }
                
                if error_message:
                    update_data["error_message"] = error_message
                    update_data["current_step"] = "failed"
                
                await queue_collection.update_one(
                    {"queue_request_id": queue_request_id},
                    {"$set": update_data}
                )
                
                logger.info(f"Successfully updated queue request {queue_request_id}")
            
        except Exception as e:
            logger.warning(f"Failed to update related queue request for deployment {deployment_id}: {e}")

# Global instance
vllm_manager = VLLMManager()
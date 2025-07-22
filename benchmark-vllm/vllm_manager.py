import asyncio
import subprocess
import tempfile
import os
import yaml
from typing import Dict, Any, List, Optional
from datetime import datetime
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from models import VLLMConfig, VLLMDeployment, VLLMDeploymentResponse
from database import get_database
from vllm_templates import create_vllm_deployment_template, create_vllm_statefulset_template, create_vllm_service_template
import logging

logger = logging.getLogger(__name__)

class VLLMManager:
    def __init__(self):
        self.k8s_client = None
        self.apps_v1 = None
        self.core_v1 = None
        self.deployments: Dict[str, VLLMDeployment] = {}
        self.db = get_database()
        self._load_kubernetes_client()
        
    async def initialize(self):
        """Initialize the VLLM manager (async initialization if needed)"""
        logger.info("VLLMManager initialized successfully")
        return True
        
    def _load_kubernetes_client(self):
        """Load Kubernetes client configuration"""
        try:
            # Try to load in-cluster config first
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except:
            try:
                # Fallback to local kubeconfig
                config.load_kube_config()
                logger.info("Loaded local Kubernetes config")
            except Exception as e:
                logger.error(f"Failed to load Kubernetes config: {e}")
                raise
        
        self.k8s_client = client.ApiClient()
        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()
        
        # Get available namespaces for debugging
        try:
            namespaces = self.core_v1.list_namespace()
            logger.info(f"Found {len(namespaces.items)} namespaces")
        except Exception as e:
            logger.warning(f"Could not list namespaces: {e}")
    
    async def deploy_vllm_with_helm(self, config: VLLMConfig, deployment_id: str, github_token: Optional[str] = None) -> VLLMDeploymentResponse:
        """Deploy vLLM using Helm chart instead of hardcoded templates"""
        try:
            logger.info(f"Starting Helm-based vLLM deployment: {deployment_id}")
            
            # Generate release name based on deployment config
            release_name = self._generate_helm_release_name(config, deployment_id)
            namespace = getattr(config, 'namespace', 'vllm')
            
            # Create Helm values from vLLM config
            helm_values = self._create_helm_values_from_config(config)
            
            # Write values to temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                yaml.dump(helm_values, f, default_flow_style=False)
                values_file = f.name
            
            try:
                # Deploy using Helm
                chart_path = self._get_vllm_chart_path(github_token)
                await self._helm_install(release_name, chart_path, namespace, values_file)
                
                # Create deployment record
                deployment = VLLMDeployment(
                    deployment_id=deployment_id,
                    config=config,
                    status="deploying",
                    helm_release_name=release_name,
                    namespace=namespace,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                self.deployments[deployment_id] = deployment
                await self._save_deployment_to_db(deployment)
                
                logger.info(f"Helm deployment started successfully: {release_name}")
                return VLLMDeploymentResponse(
                    deployment_id=deployment_id,
                    status="deploying",
                    message=f"vLLM deployment started with Helm release: {release_name}",
                    namespace=namespace,
                    helm_release_name=release_name
                )
                
            finally:
                # Clean up temporary values file
                os.unlink(values_file)
                
        except Exception as e:
            logger.error(f"Failed to deploy vLLM with Helm: {e}")
            raise
    
    def _generate_helm_release_name(self, config: VLLMConfig, deployment_id: str) -> str:
        """Generate a Helm release name based on config and deployment ID"""
        # Create a safe release name from model name and deployment ID
        model_name = config.model_name.lower().replace('/', '-').replace('_', '-')
        short_id = deployment_id[:8]  # Use first 8 chars of deployment ID
        gpu_type = "gpu" if config.gpu_resource_type != "cpu" else "cpu"
        gpu_count = config.gpu_resource_count
        
        return f"vllm-{model_name}-{short_id}-{gpu_type}-{gpu_count}"
    
    def _create_helm_values_from_config(self, config: VLLMConfig) -> Dict[str, Any]:
        """Convert VLLMConfig to Helm values"""
        values = {
            "replicaCount": 1,
            "image": {
                "repository": "vllm/vllm-openai",
                "tag": "v0.9.1",
                "pullPolicy": "IfNotPresent"
            },
            "fullnameOverride": f"vllm-{config.served_model_name}",
            "service": {
                "type": "ClusterIP",
                "port": config.port,
                "targetPort": config.port
            },
            "vllm": {
                "host": config.host,
                "port": config.port,
                "maxModelLen": config.max_model_len or 4096,
                "gpuMemoryUtilization": config.gpu_memory_utilization,
                "dtype": config.dtype,
                "trust_remote_code": config.trust_remote_code,
                "tensor_parallel_size": config.tensor_parallel_size,
                "pipeline_parallel_size": config.pipeline_parallel_size,
                "max_num_seqs": config.max_num_seqs
            },
            "env": []
        }
        
        # Add model name as command argument
        values["args"] = [
            "--model", config.model_name,
            "--served-model-name", config.served_model_name or config.model_name,
            "--host", config.host,
            "--port", str(config.port)
        ]
        
        # Add quantization if specified
        if config.quantization:
            values["args"].extend(["--quantization", config.quantization])
        
        # Add additional args
        if config.additional_args:
            for key, value in config.additional_args.items():
                if isinstance(value, bool) and value:
                    values["args"].append(f"--{key}")
                elif not isinstance(value, bool):
                    values["args"].extend([f"--{key}", str(value)])
        
        # Configure resources based on GPU requirements
        if config.gpu_resource_type != "cpu" and config.gpu_resource_count > 0:
            values["resources"] = {
                "limits": {
                    config.gpu_resource_type: config.gpu_resource_count,
                    "cpu": "4",
                    "memory": "16Gi"
                },
                "requests": {
                    config.gpu_resource_type: config.gpu_resource_count,
                    "cpu": "2",
                    "memory": "8Gi"
                }
            }
            
            # Add GPU-specific environment variables
            values["env"].extend([
                {"name": "CUDA_VISIBLE_DEVICES", "value": "0"},
                {"name": "NVIDIA_VISIBLE_DEVICES", "value": "all"}
            ])
        else:
            # CPU-only configuration
            values["resources"] = {
                "limits": {
                    "cpu": "2",
                    "memory": "4Gi"
                },
                "requests": {
                    "cpu": "1",
                    "memory": "2Gi"
                }
            }
            
            # Add CPU-specific args
            values["args"].extend([
                "--device", "cpu",
                "--enforce-eager",
                "--disable-custom-all-reduce"
            ])
            
            values["env"].extend([
                {"name": "VLLM_TARGET_DEVICE", "value": "cpu"},
                {"name": "CUDA_VISIBLE_DEVICES", "value": ""}
            ])
        
        return values
    
    def _get_vllm_chart_path(self, github_token: Optional[str] = None) -> str:
        """Get the path to the vLLM Helm chart"""
        # Look for the chart in the expected location
        possible_paths = [
            "/app/charts/thaki/vllm",  # If charts are copied to container
            "./benchmark-vllm-helm/charts/thaki/vllm",  # Relative path
            "../benchmark-vllm-helm/charts/thaki/vllm",  # Parent directory
            "charts/thaki/vllm"  # Root relative
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"Found vLLM chart at: {path}")
                return path
        
        # If not found, try to clone the charts repository
        logger.warning("vLLM chart not found locally, attempting to clone charts repository")
        return self._clone_charts_repository(github_token)
    
    def _clone_charts_repository(self, github_token: Optional[str] = None) -> str:
        """Clone the charts repository to get the vLLM chart"""
        try:
            charts_dir = "/tmp/thaki-charts"
            if os.path.exists(charts_dir):
                subprocess.run(["rm", "-rf", charts_dir], check=True)
            
            # Use provided GitHub token, fallback to environment variable
            if not github_token:
                github_token = os.getenv("GITHUB_TOKEN")
            
            if github_token:
                # Clone with authentication for private repositories
                clone_url = f"https://{github_token}@github.com/ThakiCloud/charts.git"
                logger.info("Using GitHub token for private repository access")
            else:
                # Fallback to public access (will fail for private repos)
                clone_url = "https://github.com/ThakiCloud/charts.git"
                logger.warning("No GitHub token found, attempting public clone")
            
            clone_cmd = [
                "git", "clone", 
                clone_url,
                charts_dir
            ]
            subprocess.run(clone_cmd, check=True, capture_output=True)
            
            chart_path = os.path.join(charts_dir, "thaki", "vllm")
            if os.path.exists(chart_path):
                logger.info(f"Successfully cloned charts repository to: {chart_path}")
                return chart_path
            else:
                raise FileNotFoundError(f"vLLM chart not found in cloned repository: {chart_path}")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to clone charts repository: {e}")
            raise RuntimeError(f"Could not clone charts repository: {e}")
    
    async def _helm_install(self, release_name: str, chart_path: str, namespace: str, values_file: str):
        """Execute Helm install command"""
        try:
            # Ensure namespace exists
            await self._ensure_namespace_exists(namespace)
            
            # Build Helm install command
            helm_cmd = [
                "helm", "install", release_name, chart_path,
                "--namespace", namespace,
                "--values", values_file,
                "--wait",
                "--timeout", "10m"
            ]
            
            logger.info(f"Executing Helm install: {' '.join(helm_cmd)}")
            
            # Execute Helm command
            result = subprocess.run(
                helm_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Helm install output: {result.stdout}")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Helm install failed: {e.stderr}")
            raise RuntimeError(f"Helm install failed: {e.stderr}")
    
    async def _ensure_namespace_exists(self, namespace: str):
        """Ensure the namespace exists, create if it doesn't"""
        try:
            self.core_v1.read_namespace(name=namespace)
            logger.info(f"Namespace {namespace} already exists")
        except ApiException as e:
            if e.status == 404:
                logger.info(f"Creating namespace: {namespace}")
                namespace_manifest = client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=namespace)
                )
                self.core_v1.create_namespace(body=namespace_manifest)
            else:
                logger.error(f"Error checking namespace {namespace}: {e}")
                raise
    
    async def _save_deployment_to_db(self, deployment: VLLMDeployment):
        """Save deployment info to database"""
        try:
            collection = self.db.vllm_helm_deployments
            deployment_dict = deployment.dict()
            deployment_dict['config'] = deployment.config.dict()  # Ensure config is serializable
            await collection.insert_one(deployment_dict)
            logger.info(f"Saved deployment {deployment.deployment_id} to database")
        except Exception as e:
            logger.error(f"Failed to save deployment to database: {e}")
    
    async def get_deployment_status(self, deployment_id: str) -> Optional[VLLMDeployment]:
        """Get deployment status"""
        deployment = self.deployments.get(deployment_id)
        if deployment:
            return deployment
            
        # Try to load from database
        try:
            collection = self.db.vllm_helm_deployments
            deployment_doc = await collection.find_one({"deployment_id": deployment_id})
            if deployment_doc:
                # Remove MongoDB _id field
                deployment_doc.pop('_id', None)
                # Reconstruct VLLMDeployment object
                config_dict = deployment_doc.pop('config')
                config = VLLMConfig(**config_dict)
                deployment_doc['config'] = config
                deployment = VLLMDeployment(**deployment_doc)
                self.deployments[deployment_id] = deployment
                return deployment
        except Exception as e:
            logger.error(f"Error loading deployment {deployment_id} from database: {e}")
            
        return None
    
    async def list_deployments(self) -> Dict[str, VLLMDeployment]:
        """List all deployments"""
        return self.deployments.copy()
    
    async def stop_helm_deployment(self, deployment_id: str) -> bool:
        """Stop a Helm-based vLLM deployment"""
        try:
            deployment = await self.get_deployment_status(deployment_id)
            if not deployment or not deployment.helm_release_name:
                logger.error(f"Deployment {deployment_id} not found or not a Helm deployment")
                return False
            
            # Execute Helm uninstall
            helm_cmd = [
                "helm", "uninstall", deployment.helm_release_name,
                "--namespace", deployment.namespace
            ]
            
            logger.info(f"Executing Helm uninstall: {' '.join(helm_cmd)}")
            
            result = subprocess.run(
                helm_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Helm uninstall output: {result.stdout}")
            
            # Update deployment status
            deployment.status = "stopped"
            deployment.updated_at = datetime.utcnow()
            self.deployments[deployment_id] = deployment
            
            # Update in database
            await self._update_deployment_in_db(deployment)
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Helm uninstall failed: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Failed to stop Helm deployment {deployment_id}: {e}")
            return False
    
    async def _update_deployment_in_db(self, deployment: VLLMDeployment):
        """Update deployment info in database"""
        try:
            collection = self.db.vllm_helm_deployments
            deployment_dict = deployment.dict()
            deployment_dict['config'] = deployment.config.dict()  # Ensure config is serializable
            
            await collection.update_one(
                {"deployment_id": deployment.deployment_id},
                {"$set": deployment_dict}
            )
            logger.info(f"Updated deployment {deployment.deployment_id} in database")
        except Exception as e:
            logger.error(f"Failed to update deployment in database: {e}")

    async def wait_for_helm_deployment_ready(self, deployment_id: str, timeout: int = 600, max_failures: int = 3, failure_retry_delay: int = 30):
        """Wait for Helm-based vLLM deployment to be ready with failure tracking"""
        start_time = datetime.utcnow()
        failure_count = 0
        consecutive_failures = 0
        last_status = None
        
        logger.info(f"Waiting for Helm vLLM deployment {deployment_id} to be ready (timeout: {timeout}s, max_failures: {max_failures})")
        
        while True:
            try:
                deployment = await self.get_deployment_status(deployment_id)
                if not deployment:
                    raise Exception(f"Deployment {deployment_id} not found")
                
                # Check Helm release status
                helm_status = await self._check_helm_release_status(deployment.helm_release_name, deployment.namespace)
                current_status = helm_status.get('status', 'unknown').lower()
                
                logger.debug(f"Helm deployment {deployment_id} status: {current_status}")
                
                if current_status in ["deployed", "running"]:
                    # Additional check: verify pod is actually ready
                    pod_ready = await self._check_pod_readiness(deployment.helm_release_name, deployment.namespace)
                    if pod_ready:
                        logger.info(f"Helm vLLM deployment {deployment_id} is ready")
                        # Update deployment status
                        deployment.status = "running"
                        deployment.updated_at = datetime.utcnow()
                        self.deployments[deployment_id] = deployment
                        await self._update_deployment_in_db(deployment)
                        return
                
                if current_status in ["failed", "error", "uninstalling", "superseded"]:
                    failure_count += 1
                    consecutive_failures += 1
                    
                    logger.warning(f"Helm deployment {deployment_id} failed with status: {current_status} (failure #{failure_count})")
                    
                    # Check if we've exceeded maximum failures
                    if failure_count >= max_failures:
                        logger.error(f"Helm deployment {deployment_id} has failed {failure_count} times, exceeding maximum of {max_failures}")
                        
                        # Attempt to clean up the failed deployment
                        try:
                            await self.stop_helm_deployment(deployment_id)
                            logger.info(f"Successfully cleaned up failed Helm deployment {deployment_id}")
                        except Exception as cleanup_error:
                            logger.error(f"Failed to clean up Helm deployment {deployment_id}: {cleanup_error}")
                        
                        # Update deployment status
                        deployment.status = "failed"
                        deployment.error_message = f"Deployment failed {failure_count} times, exceeding maximum failures ({max_failures})"
                        deployment.updated_at = datetime.utcnow()
                        self.deployments[deployment_id] = deployment
                        await self._update_deployment_in_db(deployment)
                        
                        raise Exception(f"Helm deployment {deployment_id} failed {failure_count} times, exceeding maximum failures ({max_failures}). Deployment has been terminated.")
                    
                    # Wait longer before retrying after failure
                    logger.info(f"Helm deployment {deployment_id} failed, waiting {failure_retry_delay} seconds before next check...")
                    await asyncio.sleep(failure_retry_delay)
                    continue
                
                # Reset consecutive failures if deployment is recovering
                if current_status in ["pending-install", "pending-upgrade"] and last_status in ["failed", "error"]:
                    consecutive_failures = 0
                    logger.info(f"Helm deployment {deployment_id} is recovering from failure")
                
                last_status = current_status
                
                # Check timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    logger.error(f"Timeout waiting for Helm deployment {deployment_id} to be ready after {elapsed}s (timeout: {timeout}s)")
                    
                    # Attempt to clean up the timed-out deployment
                    try:
                        await self.stop_helm_deployment(deployment_id)
                        logger.info(f"Successfully cleaned up timed-out Helm deployment {deployment_id}")
                    except Exception as cleanup_error:
                        logger.error(f"Failed to clean up timed-out Helm deployment {deployment_id}: {cleanup_error}")
                    
                    # Update deployment status
                    deployment.status = "failed"
                    deployment.error_message = f"Timeout waiting for deployment to be ready (timeout: {timeout}s)"
                    deployment.updated_at = datetime.utcnow()
                    self.deployments[deployment_id] = deployment
                    await self._update_deployment_in_db(deployment)
                    
                    raise Exception(f"Timeout waiting for Helm deployment {deployment_id} to be ready (timeout: {timeout}s). Deployment has been terminated.")
                
                # Normal polling interval
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                if "failed" in str(e).lower() or "timeout" in str(e).lower() or "exceeding maximum failures" in str(e).lower():
                    # These are expected failures, re-raise them
                    raise
                else:
                    # Unexpected error, log and continue
                    logger.warning(f"Unexpected error checking Helm deployment status: {e}")
                    await asyncio.sleep(10)
    
    async def _check_helm_release_status(self, release_name: str, namespace: str) -> Dict[str, Any]:
        """Check Helm release status"""
        try:
            helm_cmd = [
                "helm", "status", release_name,
                "--namespace", namespace,
                "--output", "json"
            ]
            
            result = subprocess.run(
                helm_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            import json
            status_data = json.loads(result.stdout)
            return {
                'status': status_data.get('info', {}).get('status', 'unknown'),
                'description': status_data.get('info', {}).get('description', ''),
                'notes': status_data.get('info', {}).get('notes', '')
            }
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get Helm release status: {e.stderr}")
            return {'status': 'error', 'description': f'Failed to get status: {e.stderr}'}
        except Exception as e:
            logger.error(f"Error checking Helm release status: {e}")
            return {'status': 'unknown', 'description': str(e)}
    
    async def _check_pod_readiness(self, release_name: str, namespace: str) -> bool:
        """Check if pods from Helm release are ready"""
        try:
            # Get pods with the release label
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"app.kubernetes.io/instance={release_name}"
            )
            
            if not pods.items:
                logger.warning(f"No pods found for Helm release {release_name}")
                return False
            
            for pod in pods.items:
                pod_name = pod.metadata.name
                pod_status = pod.status.phase
                
                if pod_status != "Running":
                    logger.debug(f"Pod {pod_name} status: {pod_status}")
                    return False
                
                # Check container readiness
                if pod.status.container_statuses:
                    for container_status in pod.status.container_statuses:
                        if not container_status.ready:
                            logger.debug(f"Container {container_status.name} in pod {pod_name} not ready")
                            return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking pod readiness for release {release_name}: {e}")
            return False

# Global instance
vllm_manager = VLLMManager()
import yaml
import logging
import asyncio
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import io
import base64
import tempfile
import os

from models import ResourceType, DeploymentStatus, JobStatusResponse
from config import KUBECONFIG_PATH, DEFAULT_NAMESPACE, LOG_TAIL_LINES, DEPLOYMENT_TIMEOUT

logger = logging.getLogger(__name__)

class KubernetesClient:
    def __init__(self):
        self.api_client = None
        self.apps_v1 = None
        self.core_v1 = None
        self.batch_v1 = None
        self.is_connected = False
        
    async def initialize(self):
        """Initialize Kubernetes client."""
        try:
            # Try to load in-cluster config first, then fall back to kubeconfig
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes configuration")
            except config.ConfigException:
                # Try to load from kubeconfig file
                try:
                    if KUBECONFIG_PATH and os.path.exists(KUBECONFIG_PATH):
                        config.load_kube_config(config_file=KUBECONFIG_PATH)
                        logger.info(f"Loaded Kubernetes configuration from {KUBECONFIG_PATH}")
                    else:
                        # Try default kubeconfig location
                        config.load_kube_config()
                        logger.info("Loaded Kubernetes configuration from default location")
                except Exception as kube_error:
                    logger.warning(f"No valid Kubernetes configuration found: {kube_error}")
                    raise Exception(f"No valid Kubernetes configuration: {kube_error}")
            
            self.api_client = client.ApiClient()
            self.apps_v1 = client.AppsV1Api()
            self.core_v1 = client.CoreV1Api()
            self.batch_v1 = client.BatchV1Api()
            
            # Test connection
            connection_success = await self.test_connection()
            if connection_success:
                self.is_connected = True
                logger.info("Kubernetes client initialized successfully")
            else:
                self.is_connected = False
                raise Exception("Kubernetes connection test failed")
            
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            self.is_connected = False
            raise

    async def test_connection(self):
        """Test Kubernetes connection."""
        try:
            # Use a simple API call to test connection
            namespaces = self.core_v1.list_namespace(limit=1)
            logger.info("Kubernetes connection test successful")
            return True
        except Exception as e:
            logger.error(f"Kubernetes connection test failed: {e}")
            return False

    def parse_yaml_content(self, yaml_content: str) -> List[Dict[str, Any]]:
        """Parse YAML content into Kubernetes resources."""
        try:
            # Parse YAML content (can contain multiple documents)
            resources = []
            for document in yaml.safe_load_all(yaml_content):
                if document:  # Skip empty documents
                    resources.append(document)
            return resources
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML content: {e}")

    def get_resource_type(self, resource: Dict[str, Any]) -> ResourceType:
        """Determine resource type from Kubernetes resource."""
        kind = resource.get('kind', '').lower()
        
        if kind == 'job':
            return ResourceType.JOB
        elif kind == 'deployment':
            return ResourceType.DEPLOYMENT
        elif kind == 'service':
            return ResourceType.SERVICE
        elif kind == 'configmap':
            return ResourceType.CONFIGMAP
        elif kind == 'secret':
            return ResourceType.SECRET
        else:
            return ResourceType.UNKNOWN

    async def deploy_yaml(self, yaml_content: str, namespace: str = DEFAULT_NAMESPACE) -> Dict[str, Any]:
        """Deploy Kubernetes resources from YAML content."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            # Ensure namespace exists before deploying resources
            await self.ensure_namespace_exists(namespace)
            
            resources = self.parse_yaml_content(yaml_content)
            deployed_resources = []
            
            for resource in resources:
                # Set namespace if not specified
                if 'namespace' not in resource.get('metadata', {}):
                    resource.setdefault('metadata', {})['namespace'] = namespace
                
                kind = resource.get('kind')
                api_version = resource.get('apiVersion')
                name = resource.get('metadata', {}).get('name')
                resource_type = self.get_resource_type(resource)
                
                # Deploy based on resource type
                # Remove apiVersion and kind from resource body since they're not needed for client objects
                resource_body = {k: v for k, v in resource.items() if k not in ['apiVersion', 'kind']}
                
                try:
                    if kind == 'Job':
                        body = client.V1Job(**resource_body)
                        result = self.batch_v1.create_namespaced_job(namespace=namespace, body=body)
                        deployed_resources.append((name, kind, resource_type))
                        
                    elif kind == 'Deployment':
                        body = client.V1Deployment(**resource_body)
                        result = self.apps_v1.create_namespaced_deployment(namespace=namespace, body=body)
                        deployed_resources.append((name, kind, resource_type))
                        
                    elif kind == 'Service':
                        body = client.V1Service(**resource_body)
                        result = self.core_v1.create_namespaced_service(namespace=namespace, body=body)
                        deployed_resources.append((name, kind, resource_type))
                        
                    elif kind == 'ConfigMap':
                        body = client.V1ConfigMap(**resource_body)
                        result = self.core_v1.create_namespaced_config_map(namespace=namespace, body=body)
                        deployed_resources.append((name, kind, resource_type))
                        
                    elif kind == 'Secret':
                        body = client.V1Secret(**resource_body)
                        result = self.core_v1.create_namespaced_secret(namespace=namespace, body=body)
                        deployed_resources.append((name, kind, resource_type))
                        
                    else:
                        logger.warning(f"Unsupported resource type: {kind}")
                        continue
                    
                    logger.info(f"Successfully deployed {kind} '{name}' in namespace '{namespace}'")
                    
                except ApiException as api_e:
                    if api_e.status == 409:  # Conflict - resource already exists
                        logger.warning(f"{kind} '{name}' already exists in namespace '{namespace}', attempting to handle conflict")
                        
                        # For Jobs, we can't update them, so we might want to delete and recreate
                        # or just skip if it's the same job
                        if kind == 'Job':
                            # Check if the job is completed, if so we can delete it and create new one
                            try:
                                existing_job = self.batch_v1.read_namespaced_job(name=name, namespace=namespace)
                                if existing_job.status.conditions:
                                    # Job has completed, delete it and create new one
                                    for condition in existing_job.status.conditions:
                                        if condition.type in ['Complete', 'Failed']:
                                            logger.info(f"Deleting completed/failed job '{name}' to create new one")
                                            self.batch_v1.delete_namespaced_job(
                                                name=name, 
                                                namespace=namespace, 
                                                propagation_policy='Background'
                                            )
                                            # Wait a moment for deletion to propagate
                                            await asyncio.sleep(2)
                                            # Now try to create the job again
                                            body = client.V1Job(**resource_body)
                                            result = self.batch_v1.create_namespaced_job(namespace=namespace, body=body)
                                            deployed_resources.append((name, kind, resource_type))
                                            logger.info(f"Successfully recreated {kind} '{name}' in namespace '{namespace}'")
                                            break
                                else:
                                    # Job is still running, skip creation
                                    logger.info(f"Job '{name}' is still running, skipping creation")
                                    deployed_resources.append((name, kind, resource_type))
                            except Exception as read_error:
                                logger.warning(f"Could not read existing job '{name}': {read_error}")
                                # Just skip this resource
                                deployed_resources.append((name, kind, resource_type))
                        
                        else:
                            # For other resources, we can try to update them or just skip
                            logger.info(f"Resource '{name}' already exists, skipping creation")
                            deployed_resources.append((name, kind, resource_type))
                    else:
                        # Other API errors should still be raised
                        logger.error(f"Kubernetes API error for {kind} '{name}': {api_e}")
                        raise api_e
            
            # Return info about the first deployed resource (usually the main one)
            if deployed_resources:
                name, kind, resource_type = deployed_resources[0]
                return {
                    "resource_name": name,
                    "resource_type": resource_type,
                    "kind": kind
                }
            else:
                raise Exception("No resources were deployed")
                
        except ApiException as e:
            logger.error(f"Kubernetes API error during deployment: {e}")
            raise Exception(f"Deployment failed: {e.reason}")
        except Exception as e:
            logger.error(f"Deployment error: {e}")
            raise

    async def delete_yaml(self, yaml_content: str, namespace: str = DEFAULT_NAMESPACE) -> Dict[str, Any]:
        """Delete Kubernetes resources from YAML content."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            resources = self.parse_yaml_content(yaml_content)
            deleted_resources = []
            
            for resource in resources:
                kind = resource.get('kind')
                name = resource.get('metadata', {}).get('name')
                resource_namespace = resource.get('metadata', {}).get('namespace', namespace)
                
                try:
                    # Delete based on resource type
                    if kind == 'Job':
                        self.batch_v1.delete_namespaced_job(
                            name=name, 
                            namespace=resource_namespace,
                            propagation_policy='Background'
                        )
                        deleted_resources.append({"name": name, "kind": kind, "namespace": resource_namespace})
                        
                    elif kind == 'Deployment':
                        self.apps_v1.delete_namespaced_deployment(
                            name=name, 
                            namespace=resource_namespace,
                            propagation_policy='Background'
                        )
                        deleted_resources.append({"name": name, "kind": kind, "namespace": resource_namespace})
                        
                    elif kind == 'Service':
                        self.core_v1.delete_namespaced_service(name=name, namespace=resource_namespace)
                        deleted_resources.append({"name": name, "kind": kind, "namespace": resource_namespace})
                        
                    elif kind == 'ConfigMap':
                        self.core_v1.delete_namespaced_config_map(name=name, namespace=resource_namespace)
                        deleted_resources.append({"name": name, "kind": kind, "namespace": resource_namespace})
                        
                    elif kind == 'Secret':
                        self.core_v1.delete_namespaced_secret(name=name, namespace=resource_namespace)
                        deleted_resources.append({"name": name, "kind": kind, "namespace": resource_namespace})
                        
                    else:
                        logger.warning(f"Unsupported resource type for deletion: {kind}")
                        continue
                    
                    logger.info(f"Successfully deleted {kind} '{name}' from namespace '{resource_namespace}'")
                    
                except ApiException as e:
                    if e.status == 404:
                        logger.info(f"{kind} '{name}' not found in namespace '{resource_namespace}' (already deleted)")
                        deleted_resources.append({"name": name, "kind": kind, "namespace": resource_namespace})
                    else:
                        logger.error(f"Failed to delete {kind} '{name}': {e}")
                        raise
            
            return {"deleted_resources": deleted_resources}
            
        except Exception as e:
            logger.error(f"Deletion error: {e}")
            raise

    async def get_job_logs(self, job_name: str, namespace: str = DEFAULT_NAMESPACE, 
                          tail_lines: int = LOG_TAIL_LINES, follow: bool = False) -> List[str]:
        """Get logs from a job."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            # Get pods for the job
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"job-name={job_name}"
            )

            if not pods.items:
                raise Exception(f"No pods found for job '{job_name}' in namespace '{namespace}'")

            all_logs = []
            
            for pod in pods.items:
                pod_name = pod.metadata.name
                
                try:
                    # Get logs from the pod
                    log_response = self.core_v1.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        tail_lines=tail_lines,
                        follow=follow
                    )
                    
                    # Split logs into lines and add pod prefix
                    log_lines = log_response.split('\n') if log_response else []
                    for line in log_lines:
                        if line.strip():  # Skip empty lines
                            all_logs.append(f"[{pod_name}] {line}")
                            
                except ApiException as e:
                    if e.status == 400:
                        # Pod might not have started yet or no logs available
                        all_logs.append(f"[{pod_name}] No logs available yet")
                    else:
                        logger.error(f"Error getting logs from pod {pod_name}: {e}")
                        all_logs.append(f"[{pod_name}] Error getting logs: {e}")

            return all_logs

        except Exception as e:
            logger.error(f"Error getting job logs: {e}")
            raise

    async def get_job_status(self, job_name: str, namespace: str = DEFAULT_NAMESPACE) -> JobStatusResponse:
        """Get job status."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            # Get the job
            job = self.batch_v1.read_namespaced_job(name=job_name, namespace=namespace)
            
            # Determine status based on job conditions first
            status = DeploymentStatus.PENDING
            if job.status.conditions:
                for condition in job.status.conditions:
                    if condition.type == "Complete" and condition.status == "True":
                        status = DeploymentStatus.COMPLETED
                        break
                    elif condition.type == "Failed" and condition.status == "True":
                        status = DeploymentStatus.FAILED
                        break
            
            # If no definitive condition, check actual pod states
            if status == DeploymentStatus.PENDING:
                try:
                    # Get pods for the job
                    pods = self.core_v1.list_namespaced_pod(
                        namespace=namespace,
                        label_selector=f"job-name={job_name}"
                    )
                    
                    if not pods.items:
                        status = DeploymentStatus.PENDING
                    else:
                        # Check pod states
                        running_pods = 0
                        failed_pods = 0
                        succeeded_pods = 0
                        pending_pods = 0
                        
                        for pod in pods.items:
                            pod_phase = pod.status.phase
                            if pod_phase == "Running":
                                running_pods += 1
                            elif pod_phase == "Failed":
                                failed_pods += 1
                            elif pod_phase == "Succeeded":
                                succeeded_pods += 1
                            else:
                                pending_pods += 1
                        
                        # Determine job status based on pod states
                        if running_pods > 0:
                            status = DeploymentStatus.RUNNING
                        elif succeeded_pods > 0 and failed_pods == 0 and running_pods == 0 and pending_pods == 0:
                            status = DeploymentStatus.COMPLETED
                        elif failed_pods > 0 and running_pods == 0:
                            # If all pods failed or some failed with no running pods
                            if succeeded_pods == 0 and pending_pods == 0:
                                status = DeploymentStatus.FAILED
                            else:
                                status = DeploymentStatus.RUNNING  # Some pods still might recover
                        elif pending_pods > 0:
                            status = DeploymentStatus.PENDING
                        else:
                            status = DeploymentStatus.PENDING
                            
                except Exception as pod_check_error:
                    logger.warning(f"Could not check pod states for job {job_name}: {pod_check_error}")
                    # Fallback to job active count
                    if job.status.active and job.status.active > 0:
                        status = DeploymentStatus.RUNNING

            return JobStatusResponse(
                job_name=job_name,
                namespace=namespace,
                status=status,
                phase=None,  # Jobs don't have phases like pods
                start_time=job.status.start_time,
                completion_time=job.status.completion_time,
                active_pods=job.status.active or 0,
                succeeded_pods=job.status.succeeded or 0,
                failed_pods=job.status.failed or 0
            )

        except ApiException as e:
            if e.status == 404:
                raise Exception(f"Job '{job_name}' not found in namespace '{namespace}'")
            else:
                logger.error(f"Error getting job status: {e}")
                raise
        except Exception as e:
            logger.error(f"Error getting job status: {e}")
            raise

    async def get_kubernetes_version(self) -> Optional[str]:
        """Get Kubernetes cluster version."""
        try:
            if not self.is_connected or self.core_v1 is None:
                return None
                
            version_info = self.core_v1.get_api_resources()
            return "Connected"  # Simplified version info
        except Exception as e:
            logger.warning(f"Could not get Kubernetes version: {e}")
            return None

    async def get_pod_status(self, pod_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get pod status."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            return pod.status.phase.lower() if pod.status.phase else "unknown"
        except ApiException as e:
            if e.status == 404:
                return "deleted"
            else:
                logger.error(f"Error getting pod status: {e}")
                return "unknown"
        except Exception as e:
            logger.error(f"Error getting pod status: {e}")
            return "unknown"

    async def get_deployment_status(self, deployment_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get deployment status."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            deployment = self.apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
            
            # Check deployment conditions
            if deployment.status.conditions:
                for condition in deployment.status.conditions:
                    if condition.type == "Available" and condition.status == "True":
                        return "running"
                    elif condition.type == "Progressing" and condition.status == "False":
                        return "failed"
            
            # Check replica status
            if deployment.status.ready_replicas and deployment.status.ready_replicas > 0:
                return "running"
            elif deployment.status.replicas and deployment.status.replicas > 0:
                return "pending"
            else:
                return "unknown"
                
        except ApiException as e:
            if e.status == 404:
                return "deleted"
            else:
                logger.error(f"Error getting deployment status: {e}")
                return "unknown"
        except Exception as e:
            logger.error(f"Error getting deployment status: {e}")
            return "unknown"

    async def get_service_status(self, service_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get service status."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            service = self.core_v1.read_namespaced_service(name=service_name, namespace=namespace)
            return "running"  # Services are generally running if they exist
        except ApiException as e:
            if e.status == 404:
                return "deleted"
            else:
                logger.error(f"Error getting service status: {e}")
                return "unknown"
        except Exception as e:
            logger.error(f"Error getting service status: {e}")
            return "unknown"

    async def get_job_pod_for_terminal(self, job_name: str, namespace: str = DEFAULT_NAMESPACE, 
                                     pod_name: Optional[str] = None) -> Dict[str, Any]:
        """Get pod information for terminal access."""
        if not self.is_connected:
            raise Exception("Kubernetes client not connected")

        try:
            if pod_name:
                # Get specific pod
                pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                pods = [pod]
            else:
                # Get pods for the job
                pods_list = self.core_v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"job-name={job_name}"
                )
                pods = pods_list.items

            if not pods:
                raise Exception(f"No pods found for job '{job_name}' in namespace '{namespace}'")

            # Find a running pod (prefer running pods for terminal access)
            target_pod = None
            for pod in pods:
                if pod.status.phase == "Running":
                    target_pod = pod
                    break
            
            # If no running pod, use the first available pod
            if not target_pod:
                target_pod = pods[0]

            # Get container names
            containers = [container.name for container in target_pod.spec.containers]

            return {
                "pod_name": target_pod.metadata.name,
                "containers": containers,
                "status": target_pod.status.phase
            }

        except Exception as e:
            logger.error(f"Error getting job pod for terminal: {e}")
            raise

    async def ensure_namespace_exists(self, namespace: str):
        """Ensure the specified namespace exists, create it if it doesn't."""
        try:
            # Try to get the namespace
            self.core_v1.read_namespace(name=namespace)
            logger.info(f"Namespace '{namespace}' already exists")
        except ApiException as e:
            if e.status == 404:  # Namespace doesn't exist
                try:
                    # Create the namespace
                    namespace_body = client.V1Namespace(
                        metadata=client.V1ObjectMeta(
                            name=namespace,
                            labels={
                                "created-by": "vllm-deployer",
                                "auto-created": "true"
                            }
                        )
                    )
                    self.core_v1.create_namespace(body=namespace_body)
                    logger.info(f"Successfully created namespace: {namespace}")
                except ApiException as create_error:
                    if create_error.status == 409:  # Namespace already exists (race condition)
                        logger.info(f"Namespace '{namespace}' already exists (created by another process)")
                    else:
                        logger.error(f"Failed to create namespace {namespace}: {create_error}")
                        raise Exception(f"Failed to create namespace {namespace}: {create_error}")
            else:
                logger.error(f"Error checking namespace {namespace}: {e}")
                raise Exception(f"Error checking namespace {namespace}: {e}")

    async def get_cluster_info(self) -> Optional[Dict[str, Any]]:
        """Get cluster information for health checks."""
        if not self.is_connected:
            return None
        
        try:
            # Get cluster version information
            version_info = self.core_v1.get_api_resources()
            
            # Get basic cluster info
            cluster_info = {
                "version": "available",
                "connected": True,
                "api_server": "accessible"
            }
            
            return cluster_info
            
        except Exception as e:
            logger.error(f"Failed to get cluster info: {e}")
            return None

    async def delete_job(self, job_name: str, namespace: str = DEFAULT_NAMESPACE) -> bool:
        """Delete a specific job by name"""
        if not self.is_connected:
            logger.error("Kubernetes client not connected")
            return False
        
        try:
            logger.info(f"Deleting job '{job_name}' in namespace '{namespace}'")
            
            # Delete the job with background propagation policy
            self.batch_v1.delete_namespaced_job(
                name=job_name,
                namespace=namespace,
                propagation_policy='Background'
            )
            
            logger.info(f"Successfully deleted job '{job_name}' from namespace '{namespace}'")
            return True
            
        except ApiException as e:
            if e.status == 404:
                logger.info(f"Job '{job_name}' not found in namespace '{namespace}' (already deleted)")
                return True  # Consider this a success since the job is gone
            else:
                logger.error(f"Failed to delete job '{job_name}': {e.reason}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error deleting job '{job_name}': {e}")
            return False

# Create global instance
k8s_client = KubernetesClient() 
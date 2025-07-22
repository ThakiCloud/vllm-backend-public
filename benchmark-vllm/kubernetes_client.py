import os
import yaml
import logging
from typing import Dict, Any, Optional, List
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from config import KUBECONFIG, VLLM_NAMESPACE, KUBERNETES_SERVICE_ACCOUNT

logger = logging.getLogger(__name__)

class KubernetesClient:
    def __init__(self):
        self.v1 = None
        self.apps_v1 = None
        self.namespace = VLLM_NAMESPACE
        self.service_account = KUBERNETES_SERVICE_ACCOUNT
        
    async def initialize(self):
        """Initialize Kubernetes client"""
        try:
            if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount'):
                # Running inside a pod
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config")
            else:
                # Running outside cluster
                if KUBECONFIG:
                    config.load_kube_config(config_file=KUBECONFIG)
                else:
                    config.load_kube_config()
                logger.info("Loaded Kubernetes config from kubeconfig")
            
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            
            # Test connection
            await self._test_connection()
            logger.info("Kubernetes client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise
    
    async def _test_connection(self):
        """Test Kubernetes connection"""
        try:
            # Try to list namespaces to test connection
            namespaces = self.v1.list_namespace()
            logger.info(f"Found {len(namespaces.items)} namespaces")
            
            # Check if vllm namespace exists
            vllm_namespace_exists = any(ns.metadata.name == self.namespace for ns in namespaces.items)
            if not vllm_namespace_exists:
                logger.warning(f"Namespace '{self.namespace}' not found. Creating it...")
                await self._create_namespace()
            
        except ApiException as e:
            logger.error(f"Kubernetes API error: {e}")
            raise
    
    async def _create_namespace(self):
        """Create vllm namespace if it doesn't exist"""
        try:
            namespace = client.V1Namespace(
                metadata=client.V1ObjectMeta(name=self.namespace)
            )
            self.v1.create_namespace(namespace)
            logger.info(f"Created namespace: {self.namespace}")
        except ApiException as e:
            if e.status == 409:  # Namespace already exists
                logger.info(f"Namespace {self.namespace} already exists")
            else:
                logger.error(f"Failed to create namespace: {e}")
                raise
    
    async def create_deployment(self, deployment_manifest: Dict[str, Any]) -> str:
        """Create a Kubernetes deployment"""
        try:
            # Use the manifest directly - Kubernetes client will handle conversion
            result = self.apps_v1.create_namespaced_deployment(
                namespace=self.namespace,
                body=deployment_manifest
            )
            logger.info(f"Created deployment: {result.metadata.name}")
            return result.metadata.name
        except ApiException as e:
            logger.error(f"Failed to create deployment: {e}")
            raise
    
    async def create_statefulset(self, statefulset_manifest: Dict[str, Any]) -> str:
        """Create a Kubernetes StatefulSet"""
        try:
            # Use the manifest directly - Kubernetes client will handle conversion
            result = self.apps_v1.create_namespaced_stateful_set(
                namespace=self.namespace,
                body=statefulset_manifest
            )
            logger.info(f"Created StatefulSet: {result.metadata.name}")
            return result.metadata.name
        except ApiException as e:
            logger.error(f"Failed to create StatefulSet: {e}")
            raise

    async def create_service(self, service_manifest: Dict[str, Any]) -> str:
        """Create a Kubernetes service"""
        try:
            # Use the manifest directly - Kubernetes client will handle conversion
            result = self.v1.create_namespaced_service(
                namespace=self.namespace,
                body=service_manifest
            )
            logger.info(f"Created service: {result.metadata.name}")
            return result.metadata.name
        except ApiException as e:
            logger.error(f"Failed to create service: {e}")
            raise
    
    async def get_deployment_status(self, deployment_name: str) -> Optional[Dict[str, Any]]:
        """Get deployment status"""
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace
            )
            
            status = {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": deployment.spec.replicas,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "available_replicas": deployment.status.available_replicas or 0,
                "conditions": []
            }
            
            if deployment.status.conditions:
                for condition in deployment.status.conditions:
                    status["conditions"].append({
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason,
                        "message": condition.message
                    })
            
            return status
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"Failed to get deployment status: {e}")
            raise
    
    async def get_statefulset_status(self, statefulset_name: str) -> Optional[Dict[str, Any]]:
        """Get StatefulSet status"""
        try:
            statefulset = self.apps_v1.read_namespaced_stateful_set(
                name=statefulset_name,
                namespace=self.namespace
            )
            
            status = {
                "name": statefulset.metadata.name,
                "namespace": statefulset.metadata.namespace,
                "replicas": statefulset.spec.replicas,
                "ready_replicas": statefulset.status.ready_replicas or 0,
                "current_replicas": statefulset.status.current_replicas or 0,
                "conditions": []
            }
            
            if statefulset.status.conditions:
                for condition in statefulset.status.conditions:
                    status["conditions"].append({
                        "type": condition.type,
                        "status": condition.status,
                        "reason": condition.reason,
                        "message": condition.message
                    })
            
            return status
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"Failed to get StatefulSet status: {e}")
            raise

    async def delete_deployment(self, deployment_name: str) -> bool:
        """Delete a deployment"""
        try:
            self.apps_v1.delete_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace
            )
            logger.info(f"Deleted deployment: {deployment_name}")
            return True
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Deployment {deployment_name} not found")
                return False
            logger.error(f"Failed to delete deployment: {e}")
            raise

    async def delete_statefulset(self, statefulset_name: str) -> bool:
        """Delete a StatefulSet"""
        try:
            self.apps_v1.delete_namespaced_stateful_set(
                name=statefulset_name,
                namespace=self.namespace
            )
            logger.info(f"Deleted StatefulSet: {statefulset_name}")
            return True
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"StatefulSet {statefulset_name} not found")
                return False
            logger.error(f"Failed to delete StatefulSet: {e}")
            raise
    
    async def delete_service(self, service_name: str) -> bool:
        """Delete a service"""
        try:
            self.v1.delete_namespaced_service(
                name=service_name,
                namespace=self.namespace
            )
            logger.info(f"Deleted service: {service_name}")
            return True
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Service {service_name} not found")
                return False
            logger.error(f"Failed to delete service: {e}")
            raise
    
    async def get_pod_logs(self, pod_name: str, container_name: str = None) -> str:
        """Get logs from a pod"""
        try:
            logs = self.v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
                container=container_name
            )
            return logs
        except ApiException as e:
            logger.error(f"Failed to get pod logs: {e}")
            raise
    
    async def get_statefulset(self, statefulset_name: str) -> Optional[Dict[str, Any]]:
        """Get StatefulSet by name"""
        try:
            statefulset = self.apps_v1.read_namespaced_stateful_set(
                name=statefulset_name,
                namespace=self.namespace
            )
            return {
                "name": statefulset.metadata.name,
                "ready_replicas": statefulset.status.ready_replicas or 0,
                "replicas": statefulset.status.replicas or 0,
                "labels": statefulset.metadata.labels or {}
            }
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"Failed to get StatefulSet {statefulset_name}: {e}")
            raise

    async def get_deployment(self, deployment_name: str) -> Optional[Dict[str, Any]]:
        """Get Deployment by name"""
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace
            )
            return {
                "name": deployment.metadata.name,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "replicas": deployment.status.replicas or 0,
                "labels": deployment.metadata.labels or {}
            }
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"Failed to get Deployment {deployment_name}: {e}")
            raise

    async def get_pod_status(self, pod_name: str) -> Optional[Dict[str, Any]]:
        """Get Pod status by name"""
        try:
            pod = self.v1.read_namespaced_pod(
                name=pod_name,
                namespace=self.namespace
            )
            
            # Check if pod is ready
            ready = False
            if pod.status.conditions:
                for condition in pod.status.conditions:
                    if condition.type == "Ready" and condition.status == "True":
                        ready = True
                        break
            
            return {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "ready": ready,
                "labels": pod.metadata.labels or {}
            }
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"Failed to get Pod {pod_name}: {e}")
            raise

    async def list_pods_by_label(self, label_selector: str) -> list:
        """List pods by label selector"""
        try:
            pods = self.v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector
            )
            return pods.items
        except ApiException as e:
            logger.error(f"Failed to list pods: {e}")
            raise

    async def list_deployments_by_label(self, label_selector: str = None) -> list:
        """List deployments by label selector"""
        try:
            deployments = self.apps_v1.list_namespaced_deployment(
                namespace=self.namespace,
                label_selector=label_selector
            )
            return deployments.items
        except ApiException as e:
            logger.error(f"Failed to list deployments: {e}")
            raise

    async def get_deployment_by_name(self, deployment_name: str) -> Optional[Any]:
        """Get deployment by name"""
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace
            )
            return deployment
        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"Failed to get deployment: {e}")
            raise

    async def get_deployments_using_gpu_resources(self, gpu_resource_type: str = "nvidia.com/gpu") -> list:
        """Get all deployments that are using GPU resources"""
        try:
            deployments = await self.list_deployments_by_label("app=vllm")
            gpu_deployments = []
            
            for deployment in deployments:
                containers = deployment.spec.template.spec.containers
                for container in containers:
                    if container.resources and container.resources.requests:
                        requests = container.resources.requests
                        if gpu_resource_type in requests:
                            gpu_deployments.append({
                                "deployment": deployment,
                                "gpu_count": requests[gpu_resource_type],
                                "gpu_resource_type": gpu_resource_type
                            })
                            break
            
            return gpu_deployments
        except Exception as e:
            logger.error(f"Failed to get GPU deployments: {e}")
            raise

    async def get_deployments_using_mig_resources(self, mig_resource_pattern: str = "nvidia.com/mig-") -> list:
        """Get all deployments that are using MIG GPU resources (e.g., nvidia.com/mig-3g.20gb, nvidia.com/mig-4g.24gb)"""
        try:
            deployments = await self.list_deployments_by_label("app=vllm")
            mig_deployments = []
            
            for deployment in deployments:
                containers = deployment.spec.template.spec.containers
                for container in containers:
                    if container.resources and container.resources.requests:
                        requests = container.resources.requests
                        for resource_name, resource_value in requests.items():
                            if resource_name.startswith(mig_resource_pattern):
                                mig_deployments.append({
                                    "deployment": deployment,
                                    "mig_resource_type": resource_name,
                                    "mig_count": resource_value
                                })
                                break
            
            return mig_deployments
        except Exception as e:
            logger.error(f"Failed to get MIG deployments: {e}")
            raise

    async def list_statefulsets_with_label(self, label_selector: str) -> List[Dict[str, Any]]:
        """List StatefulSets with specific label selector"""
        try:
            statefulsets = self.apps_v1.list_namespaced_stateful_set(
                namespace=self.namespace,
                label_selector=label_selector
            )
            
            result = []
            for statefulset in statefulsets.items:
                statefulset_info = {
                    "name": statefulset.metadata.name,
                    "namespace": statefulset.metadata.namespace,
                    "labels": statefulset.metadata.labels or {},
                    "created_at": statefulset.metadata.creation_timestamp,
                    "replicas": statefulset.spec.replicas,
                    "ready_replicas": statefulset.status.ready_replicas or 0,
                    "current_replicas": statefulset.status.current_replicas or 0
                }
                result.append(statefulset_info)
            
            return result
            
        except ApiException as e:
            logger.error(f"Failed to list StatefulSets: {e}")
            return []

# Global instance
kubernetes_client = KubernetesClient()
import asyncio
import subprocess
import tempfile
import os
import yaml
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from models import VLLMConfig, VLLMDeployment, VLLMDeploymentResponse
from database import get_database
from vllm_templates import create_vllm_deployment_template, create_vllm_statefulset_template, create_vllm_service_template
import logging

logger = logging.getLogger(__name__)

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

class VLLMManager:
    def __init__(self):
        self.k8s_client = None
        self.apps_v1 = None
        self.core_v1 = None
        self.deployments: Dict[str, VLLMDeployment] = {}
        self.db = get_database()
        
        # Track last custom values and deployment for smart reuse
        self.last_custom_values_hash: Optional[str] = None
        self.last_custom_values_content: Optional[str] = None
        self.last_deployment_info: Optional[Dict[str, str]] = None  # {deployment_id, release_name}
        
        self._load_kubernetes_client()
        
    async def initialize(self):
        """Initialize the VLLM manager (async initialization if needed)"""
        logger.info("VLLMManager initialized successfully")
        
        # Load last custom values tracking from database
        await self._load_last_custom_values_from_db()
        
        return True

    async def _load_last_custom_values_from_db(self):
        """Load last custom values tracking from database"""
        try:
            collection = self.db.vllm_last_custom_values
            doc = await collection.find_one({"_id": "last_custom_values"})
            
            if doc:
                self.last_custom_values_hash = doc.get("hash")
                self.last_custom_values_content = doc.get("content")
                self.last_deployment_info = doc.get("deployment_info")
                logger.info(f"💾 Loaded last custom values tracking from DB: {self.last_custom_values_hash}")
            else:
                logger.info("📋 No previous custom values tracking found in DB")
                
        except Exception as e:
            logger.warning(f"Failed to load last custom values from DB: {e}")

    async def _save_last_custom_values_to_db(self):
        """Save last custom values tracking to database"""
        try:
            collection = self.db.vllm_last_custom_values
            doc = {
                "_id": "last_custom_values",
                "hash": self.last_custom_values_hash,
                "content": self.last_custom_values_content,
                "deployment_info": self.last_deployment_info,
                "updated_at": datetime.utcnow()
            }
            
            await collection.replace_one(
                {"_id": "last_custom_values"}, 
                doc, 
                upsert=True
            )
            logger.debug(f"💾 Saved last custom values tracking to DB")
            
        except Exception as e:
            logger.warning(f"Failed to save last custom values to DB: {e}")
        
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
    
    async def deploy_vllm_with_helm(self, config: VLLMConfig, deployment_id: str, github_token: Optional[str] = None, repository_url: Optional[str] = None) -> VLLMDeploymentResponse:
        """Deploy vLLM using Helm chart with smart custom values comparison and reuse"""
        try:
            logger.info(f"Starting Helm-based vLLM deployment: {deployment_id}")
            
            # Extract model name from custom values if available
            actual_model_name = config.model_name  # Default fallback
            if config.custom_values_content:
                actual_model_name = self._extract_model_name_from_custom_values(config.custom_values_content) or config.model_name
                logger.info(f"🔄 Extracted model name from custom values: {actual_model_name}")
            
            # Calculate custom values hash for comparison
            current_values_hash = None
            if config.custom_values_content:
                import hashlib
                current_values_hash = hashlib.md5(config.custom_values_content.encode()).hexdigest()
                logger.info(f"📊 Current custom values hash: {current_values_hash}")
                
                # Check if we can reuse existing deployment
                if (self.last_custom_values_hash == current_values_hash and 
                    self.last_deployment_info is not None):
                    
                    logger.info(f"🎯 Custom values unchanged, checking if existing deployment can be reused: {self.last_deployment_info['deployment_id']}")
                    
                    # Use smart reuse logic that checks actual Kubernetes/Helm status
                    can_reuse = await self._can_reuse_existing_deployment(
                        self.last_deployment_info['release_name'], 
                        namespace
                    )
                    
                    if can_reuse:
                        logger.info(f"✅ Reusing existing deployment: {self.last_deployment_info['release_name']}")
                        
                        # Create a new deployment record for this request (but reuse the actual VLLM)
                        deployment = VLLMDeployment(
                            deployment_id=deployment_id,
                            config=config,
                            status="running",  # We validated it's running
                            helm_release_name=self.last_deployment_info['release_name'],
                            namespace=namespace,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        
                        self.deployments[deployment_id] = deployment
                        await self._save_deployment_to_db(deployment)
                        
                        return VLLMDeploymentResponse(
                            deployment_id=deployment_id,  # NEW deployment_id for this request
                            deployment_name=self.last_deployment_info['release_name'],
                            status="running",
                            config=config,
                            created_at=deployment.created_at,
                            message=f"🔄 Reusing existing vLLM deployment: {self.last_deployment_info['release_name']}"
                        )
                    else:
                        logger.info(f"❌ Cannot reuse existing deployment - will deploy new one")
                
                # Different custom values - cleanup existing deployment
                if (self.last_custom_values_hash and 
                    self.last_custom_values_hash != current_values_hash and 
                    self.last_deployment_info is not None):
                    
                    logger.info(f"🔄 Custom values changed, cleaning up existing deployment: {self.last_deployment_info['release_name']}")
                    cleanup_success = await self.cleanup_failed_helm_deployment(self.last_deployment_info['deployment_id'])
                    if cleanup_success:
                        logger.info(f"🧹 Successfully cleaned up previous deployment")
                    else:
                        logger.warning(f"⚠️ Failed to cleanup previous deployment - continuing with new deployment")
            
            # Generate deterministic release name based on custom values or config
            release_name = self._generate_deterministic_release_name(config, actual_model_name, current_values_hash)
            namespace = getattr(config, 'namespace', 'vllm')
            
            # Create Helm values from vLLM config or use custom values
            if config.custom_values_content:
                # Use provided custom values content
                logger.info("🎯 Using custom values content provided in config")
                logger.info(f"Custom values content size: {len(config.custom_values_content)} chars")
                logger.info(f"Custom values preview: {config.custom_values_content[:300]}..." if len(config.custom_values_content) > 300 else f"Custom values content: {config.custom_values_content}")
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                    f.write(config.custom_values_content)
                    values_file = f.name
                    logger.info(f"📄 Created custom values temp file: {values_file}")
                    
            elif config.custom_values_path and os.path.exists(config.custom_values_path):
                # Use custom values file
                logger.info(f"🎯 Using custom values file: {config.custom_values_path}")
                values_file = config.custom_values_path
            else:
                # Generate values from config (existing behavior)
                logger.info("🏭 Generating Helm values from VLLMConfig (no custom values found)")
                helm_values = self._create_helm_values_from_config(config, deployment_id)
                
                # Write values to temporary file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                    yaml.dump(helm_values, f, default_flow_style=False)
                    values_file = f.name
                    logger.info(f"📄 Created generated values temp file: {values_file}")
                    
            logger.info(f"📋 Final values file that will be used for Helm install: {values_file}")
            
            try:
                # Check if existing deployment conflicts with new one
                deployment_action = await self._check_and_cleanup_conflicting_helm_release(release_name, namespace, config)
                
                if deployment_action == "skip":
                    logger.info(f"✅ Same configuration already exists, skipping deployment")
                    # Return existing deployment info
                    return VLLMDeploymentResponse(
                        status="success",
                        message=f"VLLM deployment skipped - same configuration already exists: {release_name}",
                        deployment_id="skipped-same-config",
                        helm_release_name=release_name,
                        namespace=namespace,
                        service_name=f"{release_name}-service",
                        pod_name=f"{release_name}-0"
                    )
                elif deployment_action == "cleanup_and_install":
                    logger.info(f"⚠️ Different configuration detected, cleaning up existing deployment")
                    await self._cleanup_conflicting_helm_resources(release_name, namespace)
                
                # Deploy using Helm
                logger.info(f"Deploying vLLM with Helm: {release_name} {values_file}")
                chart_path = self._get_vllm_chart_path(github_token, repository_url)
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
                
                # Update last custom values tracking
                if config.custom_values_content:
                    self.last_custom_values_hash = current_values_hash
                    self.last_custom_values_content = config.custom_values_content
                    self.last_deployment_info = {
                        'deployment_id': deployment_id,
                        'release_name': release_name
                    }
                    logger.info(f"💾 Updated last custom values tracking: {current_values_hash}")
                    
                    # Save to database for persistence across restarts
                    await self._save_last_custom_values_to_db()
                
                logger.info(f"Helm deployment started successfully: {release_name}")
                return VLLMDeploymentResponse(
                    deployment_id=deployment_id,
                    deployment_name=release_name,  # Use release_name as deployment_name
                    status="deploying",
                    config=config,  # Pass the VLLMConfig
                    created_at=datetime.utcnow(),  # Add created_at timestamp
                    message=f"vLLM deployment started with Helm release: {release_name}"
                )
                
            finally:
                # Clean up temporary values file (only if we created it)
                if config.custom_values_content or (not config.custom_values_path):
                    try:
                        os.unlink(values_file)
                    except (FileNotFoundError, OSError):
                        pass  # File might not exist or already deleted
                
        except Exception as e:
            logger.error(f"Failed to deploy vLLM with Helm: {e}")
            raise

    def _extract_model_name_from_custom_values(self, custom_values_content: str) -> Optional[str]:
        """Extract model name from custom values YAML content"""
        try:
            import yaml
            values_data = yaml.safe_load(custom_values_content)
            
            # Try different possible paths for model name
            possible_paths = [
                ['vllm', 'vllm', 'model'],      # vllm.vllm.model
                ['vllm', 'model'],              # vllm.model  
                ['model'],                      # model
                ['vllm', 'vllm', 'model_name'], # vllm.vllm.model_name
                ['vllm', 'model_name'],         # vllm.model_name
                ['model_name']                  # model_name
            ]
            
            for path in possible_paths:
                try:
                    value = values_data
                    for key in path:
                        value = value[key]
                    if value and isinstance(value, str):
                        # Extract just the model name from path if it's a full path
                        model_name = value.strip('/').split('/')[-1] if '/' in value else value
                        logger.info(f"Found model in custom values at {'.'.join(path)}: {value} -> {model_name}")
                        return model_name
                except (KeyError, TypeError):
                    continue
                    
            logger.warning("Could not extract model name from custom values")
            return None
            
        except Exception as e:
            logger.warning(f"Failed to parse custom values for model name: {e}")
            return None
    
    def _generate_deterministic_release_name(self, config: VLLMConfig, actual_model_name: Optional[str] = None, current_values_hash: Optional[str] = None) -> str:
        """Generate a deterministic release name based on config, model name, and custom values hash"""
        # Use actual model name if provided, otherwise fallback to config.model_name
        model_name = actual_model_name or config.model_name
        
        # Create a safe release name from model name
        safe_model_name = model_name.lower().replace('/', '-').replace('_', '-')
        gpu_type = "gpu" if config.gpu_resource_type != "cpu" else "cpu"
        gpu_count = config.gpu_resource_count
        
        # Use custom values hash as identifier if available
        if current_values_hash:
            identifier = current_values_hash[:8]  # Use first 8 chars of hash
            release_name = f"vllm-{safe_model_name}-{identifier}-{gpu_type}-{gpu_count}"
        else:
            # Fallback: create deterministic hash from config
            import hashlib
            config_str = f"{model_name}-{gpu_type}-{gpu_count}-{config.served_model_name}"
            config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]
            release_name = f"vllm-{safe_model_name}-{config_hash}-{gpu_type}-{gpu_count}"
            
        logger.info(f"🏷️ Generated deterministic release name: {release_name} (from model: {model_name})")
        return release_name
    
    def _create_helm_values_from_config(self, config: VLLMConfig, deployment_id: str) -> Dict[str, Any]:
        """Convert VLLMConfig to Helm values"""
        # Create unique name for services/PVC but keep pod name predictable
        short_id = deployment_id[:8]
        unique_name = f"vllm-{config.served_model_name}-{short_id}"
        
        values = {
            "replicaCount": 1,
            "image": {
                "repository": "vllm/vllm-openai",
                "tag": "v0.9.1",
                "pullPolicy": "IfNotPresent"
            },
            "fullnameOverride": unique_name,
            # Add custom pod naming to keep pod name consistent
            "podNameOverride": f"vllm-{config.served_model_name}",
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
    
    def _get_vllm_chart_path(self, github_token: Optional[str] = None, repository_url: Optional[str] = None) -> str:
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
        return self._clone_charts_repository(github_token, repository_url)
    
    def _clone_charts_repository(self, github_token: Optional[str] = None, repository_url: Optional[str] = None) -> str:
        """Clone the charts repository to get the vLLM chart"""
        try:
            charts_dir = "/tmp/thaki-charts"
            if os.path.exists(charts_dir):
                subprocess.run(["rm", "-rf", charts_dir], check=True)
            
            # Use provided GitHub token, fallback to environment variable
            if not github_token:
                github_token = os.getenv("GITHUB_TOKEN")
            
            # Determine the clone URL
            if repository_url:
                # Convert GitHub API URL to clone URL if needed
                clone_url = convert_github_api_to_clone_url(repository_url)
                logger.info(f"Using provided repository URL: {repository_url} -> {clone_url}")
            else:
                # Fallback to hardcoded URL (will likely fail)
                clone_url = "https://github.com/ThakiCloud/charts.git"
                logger.warning("No repository URL provided, using hardcoded fallback")
            
            # Add authentication token if available
            if github_token and not clone_url.startswith("https://"):
                logger.warning("Cannot add authentication to non-HTTPS URL")
            elif github_token:
                # Insert token into HTTPS URL
                clone_url = clone_url.replace("https://", f"https://{github_token}@")
                logger.info("Added GitHub token for private repository access")
            else:
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
    
    async def _check_and_cleanup_conflicting_helm_release(self, release_name: str, namespace: str, new_config: VLLMConfig) -> str:
        """
        Check if existing Helm release conflicts with new deployment
        Returns: 'install', 'skip', or 'cleanup_and_install'
        """
        try:
            logger.info(f"Checking for conflicting Helm release: {release_name} in namespace: {namespace}")
            
            # Check if release exists
            check_cmd = ["helm", "list", "-n", namespace, "-o", "json"]
            result = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                logger.info(f"No existing releases found in namespace {namespace}")
                return "install"
            
            try:
                releases = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning("Failed to parse helm list output")
                return "install"
            
            # Find matching release
            existing_release = None
            for release in releases:
                if release.get("name") == release_name:
                    existing_release = release
                    break
            
            if not existing_release:
                logger.info(f"No existing release found with name: {release_name}")
                return "install"
            
            # Get detailed release information
            get_cmd = ["helm", "get", "values", release_name, "-n", namespace, "-o", "json"]
            result = subprocess.run(
                get_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                logger.warning(f"Failed to get existing release values: {result.stderr}")
                return "cleanup_and_install"
            
            try:
                existing_values = json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning("Failed to parse existing release values")
                return "cleanup_and_install"
            
            # Compare configurations
            new_model = new_config.model_name
            existing_model = None
            
            # Extract model from existing values
            if isinstance(existing_values, dict):
                # Try different possible paths for model name
                vllm_section = existing_values.get('vllm', {})
                if isinstance(vllm_section, dict):
                    existing_model = vllm_section.get('model')
                
                # Also check args array for --model parameter
                if not existing_model:
                    args = existing_values.get('args', [])
                    if isinstance(args, list):
                        for i, arg in enumerate(args):
                            if arg == '--model' and i + 1 < len(args):
                                existing_model = args[i + 1]
                                break
            
            logger.info(f"Comparing models - existing: {existing_model}, new: {new_model}")
            
            # If models are the same, skip deployment
            if existing_model and new_model and existing_model == new_model:
                logger.info(f"Same model configuration detected ({existing_model}), skipping deployment")
                return "skip"
            
            # Different models or unable to compare - cleanup and install
            logger.info(f"Different configuration detected, will cleanup and reinstall")
            return "cleanup_and_install"
            
        except Exception as e:
            logger.error(f"Error checking existing Helm release: {e}")
            # When in doubt, cleanup and install to avoid conflicts
            return "cleanup_and_install"

    async def _cleanup_conflicting_helm_resources(self, release_name: str, namespace: str):
        """Clean up conflicting Kubernetes resources before Helm install"""
        try:
            logger.info(f"Cleaning up conflicting resources for release: {release_name} in namespace: {namespace}")
            
            # First, try to uninstall existing Helm release
            await self._uninstall_helm_release(release_name, namespace)
            
            # Clean up any remaining resources that might cause conflicts
            resource_patterns = [
                f"{release_name}-sa",  # ServiceAccount
                f"vllm-{release_name.replace('vllm-', '')}-sa",  # Alternative ServiceAccount pattern
                f"{release_name}",     # Other resources with same name
            ]
            
            for pattern in resource_patterns:
                try:
                    # Clean up ServiceAccounts
                    delete_sa_cmd = ["kubectl", "delete", "serviceaccount", pattern, "-n", namespace, "--ignore-not-found=true"]
                    subprocess.run(delete_sa_cmd, capture_output=True, text=True, check=False)
                    
                    # Clean up other resources with labels
                    delete_labeled_cmd = ["kubectl", "delete", "all", "-l", f"app.kubernetes.io/instance={release_name}", "-n", namespace, "--ignore-not-found=true"]
                    subprocess.run(delete_labeled_cmd, capture_output=True, text=True, check=False)
                    
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup resource {pattern}: {cleanup_error}")
                    continue
            
            # Wait a bit for resources to be fully deleted
            await asyncio.sleep(5)
            
            logger.info(f"Cleanup completed for release: {release_name}")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            # Don't fail the deployment if cleanup fails
            pass

    async def _uninstall_helm_release(self, release_name: str, namespace: str):
        """Uninstall existing Helm release"""
        try:
            logger.info(f"Uninstalling Helm release: {release_name} from namespace: {namespace}")
            
            uninstall_cmd = ["helm", "uninstall", release_name, "-n", namespace]
            result = subprocess.run(
                uninstall_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info(f"Successfully uninstalled Helm release: {release_name}")
            else:
                logger.warning(f"Failed to uninstall Helm release {release_name}: {result.stderr}")
                
        except Exception as e:
            logger.warning(f"Error uninstalling Helm release {release_name}: {e}")
            # Don't fail if uninstall fails

    async def _helm_install(self, release_name: str, chart_path: str, namespace: str, values_file: str):
        """Execute Helm install command asynchronously (non-blocking)"""
        try:
            # Ensure namespace exists
            await self._ensure_namespace_exists(namespace)
            
            # Build Helm install command WITHOUT --wait to make it non-blocking
            helm_cmd = [
                "helm", "install", release_name, chart_path,
                "--namespace", namespace,
                "--values", values_file,
                # Removed --wait and --timeout to make it non-blocking
            ]
            
            logger.info(f"Executing Helm install (non-blocking): {' '.join(helm_cmd)}")
            
            # Execute Helm command asynchronously
            result = subprocess.run(
                helm_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Helm install initiated successfully: {result.stdout}")
            logger.info(f"🚀 Helm install command completed instantly - deployment will continue in background")
            
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
        """Wait for Helm-based vLLM deployment to be ready with failure tracking (non-blocking monitoring)"""
        start_time = datetime.utcnow()
        failure_count = 0
        consecutive_failures = 0
        last_status = None
        
        logger.info(f"🔍 Starting non-blocking monitoring for Helm deployment {deployment_id} (timeout: {timeout}s, max_failures: {max_failures})")
        
        while True:
            try:
                deployment = await self.get_deployment_status(deployment_id)
                if not deployment:
                    raise Exception(f"Deployment {deployment_id} not found")
                
                # Check Helm release status
                helm_status = await self._check_helm_release_status(deployment.helm_release_name, deployment.namespace)
                current_status = helm_status.get('status', 'unknown').lower()
                
                logger.info(f"📊 Helm deployment {deployment_id} status: {current_status}")
                
                if current_status in ["deployed", "running"]:
                    # Additional check: verify pod is actually ready
                    pod_ready = await self._check_pod_readiness(deployment.helm_release_name, deployment.namespace)
                    if pod_ready:
                        logger.info(f"✅ Helm vLLM deployment {deployment_id} is ready")
                        # Update deployment status
                        deployment.status = "running"
                        deployment.updated_at = datetime.utcnow()
                        self.deployments[deployment_id] = deployment
                        await self._update_deployment_in_db(deployment)
                        return
                
                elif current_status in ["failed", "error"]:
                    failure_count += 1
                    consecutive_failures += 1
                    logger.warning(f"⚠️ Helm deployment {deployment_id} failed (attempt {failure_count}/{max_failures})")
                    
                    if failure_count >= max_failures:
                        error_msg = f"❌ VLLM Helm deployment FAILED after {max_failures} attempts. Final status: {current_status}. This deployment will be cleaned up."
                        logger.error(f"{error_msg}")
                        
                        # Update deployment status to failed before raising exception
                        deployment.status = "failed"
                        deployment.updated_at = datetime.utcnow()
                        self.deployments[deployment_id] = deployment
                        await self._update_deployment_in_db(deployment)
                        
                        raise Exception(error_msg)
                    
                    logger.info(f"⏳ Retrying in {failure_retry_delay}s...")
                    await asyncio.sleep(failure_retry_delay)
                    continue
                
                elif current_status == "pending-install":
                    logger.info(f"⏳ Helm deployment {deployment_id} is pending installation...")
                    consecutive_failures = 0  # Reset on progress
                
                elif current_status == "pending-upgrade":
                    logger.info(f"⏳ Helm deployment {deployment_id} is pending upgrade...")
                    consecutive_failures = 0  # Reset on progress
                
                else:
                    # Unknown or transitional status
                    if current_status != last_status:
                        logger.info(f"🔄 Helm deployment {deployment_id} status changed: {last_status} -> {current_status}")
                        consecutive_failures = 0  # Reset on status change
                    
                last_status = current_status
                
                # Check timeout
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout:
                    error_msg = f"⏰ VLLM Helm deployment TIMED OUT after {timeout}s. Final status: {current_status}. This deployment will be cleaned up."
                    logger.error(f"{error_msg}")
                    
                    # Update deployment status to failed before raising exception
                    deployment.status = "failed"
                    deployment.updated_at = datetime.utcnow()
                    self.deployments[deployment_id] = deployment
                    await self._update_deployment_in_db(deployment)
                    
                    raise Exception(error_msg)
                
                # Non-blocking sleep - allows other operations to continue
                logger.debug(f"💤 Sleeping 10s before next status check (non-blocking)")
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                if "failed" in str(e).lower() or "timeout" in str(e).lower() or "exceeding maximum failures" in str(e).lower():
                    # These are expected failures, re-raise them
                    raise
                else:
                    # Unexpected error, log and continue
                    logger.warning(f"⚠️ Unexpected error checking Helm deployment status: {e}")
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

    async def cleanup_failed_helm_deployment(self, deployment_id: str) -> bool:
        """Clean up a failed Helm deployment by uninstalling the Helm release"""
        try:
            deployment = await self.get_deployment_status(deployment_id)
            if not deployment or not deployment.helm_release_name:
                logger.warning(f"Cannot cleanup deployment {deployment_id} - deployment not found or no Helm release name")
                return False
            
            logger.info(f"🧹 Cleaning up failed Helm deployment: {deployment.helm_release_name}")
            
            # Execute Helm uninstall command
            helm_cmd = [
                "helm", "uninstall", deployment.helm_release_name,
                "--namespace", deployment.namespace
            ]
            
            logger.info(f"Executing Helm cleanup: {' '.join(helm_cmd)}")
            
            result = subprocess.run(
                helm_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"✅ Helm cleanup successful: {result.stdout}")
            
            # Update deployment status
            deployment.status = "cleaned_up"
            deployment.updated_at = datetime.utcnow()
            self.deployments[deployment_id] = deployment
            await self._update_deployment_in_db(deployment)
            
            # Clear last custom values tracking if this was the tracked deployment
            if (self.last_deployment_info and 
                self.last_deployment_info.get('deployment_id') == deployment_id):
                
                logger.info(f"🧹 Clearing last custom values tracking for cleaned up deployment")
                self.last_custom_values_hash = None
                self.last_custom_values_content = None
                self.last_deployment_info = None
                await self._save_last_custom_values_to_db()
            
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Helm cleanup failed: {e.stderr}")
            # Don't raise exception - cleanup failure shouldn't stop the process
            return False
        except Exception as e:
            logger.error(f"❌ Error during Helm cleanup: {e}")
            return False

    async def _can_reuse_existing_deployment(self, release_name: str, namespace: str) -> bool:
        """Check if existing Helm deployment can be reused by verifying actual status"""
        try:
            # Check 1: Helm release status
            logger.info(f"🔍 Checking Helm release status: {release_name}")
            helm_cmd = ["helm", "status", release_name, "--namespace", namespace, "--output", "json"]
            
            result = subprocess.run(
                helm_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            helm_status = json.loads(result.stdout)
            release_status = helm_status.get("info", {}).get("status", "").lower()
            
            logger.info(f"📊 Helm release status: {release_status}")
            
            # Only reuse if Helm release is deployed
            if release_status != "deployed":
                logger.info(f"❌ Cannot reuse: Helm release status is '{release_status}', not 'deployed'")
                return False
            
            # Check 2: Kubernetes deployment status
            deployment_name = release_name  # Assuming deployment name matches release name
            logger.info(f"🔍 Checking Kubernetes deployment: {deployment_name}")
            
            try:
                deployment = self.apps_v1.read_namespaced_deployment(
                    name=deployment_name,
                    namespace=namespace
                )
                
                # Check if deployment has ready replicas
                ready_replicas = deployment.status.ready_replicas or 0
                desired_replicas = deployment.spec.replicas or 0
                
                logger.info(f"📊 Kubernetes deployment status: {ready_replicas}/{desired_replicas} replicas ready")
                
                if ready_replicas > 0 and ready_replicas == desired_replicas:
                    logger.info(f"✅ Deployment is healthy and can be reused")
                    return True
                else:
                    logger.info(f"❌ Cannot reuse: Deployment not fully ready ({ready_replicas}/{desired_replicas})")
                    return False
                    
            except Exception as k8s_error:
                logger.warning(f"⚠️ Failed to check Kubernetes deployment: {k8s_error}")
                return False
                
        except subprocess.CalledProcessError as e:
            logger.info(f"❌ Cannot reuse: Helm release not found or failed: {e.stderr}")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Error checking deployment reusability: {e}")
            return False

# Global instance
vllm_manager = VLLMManager()
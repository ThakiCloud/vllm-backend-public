from typing import Dict, Any, Optional
from models import VLLMConfig
import re

def _sanitize_k8s_name(name: str) -> str:
    """
    Kubernetes DNS-1035 규칙에 맞게 이름을 정규화합니다.
    - 소문자 알파벳과 숫자, 하이픈(-)만 허용
    - 알파벳으로 시작해야 함
    - 알파벳이나 숫자로 끝나야 함
    - 최대 63자
    """
    # 모든 특수문자를 하이픈으로 변환
    sanitized = re.sub(r'[^a-zA-Z0-9-]', '-', name)
    
    # 소문자로 변환
    sanitized = sanitized.lower()
    
    # 연속된 하이픈을 하나로 합침
    sanitized = re.sub(r'-+', '-', sanitized)
    
    # 시작과 끝의 하이픈 제거
    sanitized = sanitized.strip('-')
    
    # 숫자로 시작하는 경우 앞에 'v'를 붙임
    if sanitized and sanitized[0].isdigit():
        sanitized = 'v' + sanitized
    
    # 빈 문자열이거나 알파벳으로 시작하지 않는 경우 'model'을 앞에 붙임
    if not sanitized or not sanitized[0].isalpha():
        sanitized = 'model-' + sanitized
    
    # 63자로 제한
    if len(sanitized) > 63:
        sanitized = sanitized[:63]
        # 하이픈으로 끝나는 경우 제거
        sanitized = sanitized.rstrip('-')
    
    return sanitized

def create_vllm_statefulset_template(
    deployment_name: str,
    config: VLLMConfig,
    deployment_id: str,
    namespace: str = "vllm"
) -> Dict[str, Any]:
    """Create Kubernetes StatefulSet template for vLLM with fixed pod names"""
    
    # Build vLLM command arguments
    args = [
        "--model", config.model_name,
        "--gpu-memory-utilization", str(config.gpu_memory_utilization),
        "--max-num-seqs", str(config.max_num_seqs),
        "--block-size", str(config.block_size),
        "--tensor-parallel-size", str(config.tensor_parallel_size),
        "--pipeline-parallel-size", str(config.pipeline_parallel_size),
        "--dtype", config.dtype,
        "--port", str(config.port),
        "--host", config.host,
        "--device", "cpu",  # Force CPU mode for MacBook compatibility
        "--enforce-eager",  # Disable CUDA graph for CPU
        "--disable-custom-all-reduce",  # Disable custom all-reduce for CPU
        "--max-parallel-loading-workers", "1",  # Limit parallel loading
        "--load-format", "auto",  # Auto detect model format
        "--disable-log-stats",  # Reduce logging overhead
        "--disable-log-requests"  # Reduce logging overhead
    ]
    
    if config.trust_remote_code:
        args.append("--trust-remote-code")
    
    if config.max_model_len:
        args.extend(["--max-model-len", str(config.max_model_len)])
    
    if config.quantization:
        args.extend(["--quantization", config.quantization])
    
    if config.served_model_name:
        args.extend(["--served-model-name", config.served_model_name])
    
    # Add additional arguments
    if config.additional_args:
        for key, value in config.additional_args.items():
            if isinstance(value, bool) and value:
                args.append(f"--{key}")
            elif not isinstance(value, bool):
                args.extend([f"--{key}", str(value)])
    
    # Resource requirements based on model size and configuration
    resources = _get_resource_requirements(config)
    
    statefulset_template = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": deployment_name,
            "namespace": namespace,
            "labels": {
                "app": "vllm",
                "deployment-id": deployment_id,
                "model": _sanitize_k8s_name(config.model_name)
            }
        },
        "spec": {
            "serviceName": f"{deployment_name}-headless",
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "app": "vllm",
                    "deployment-id": deployment_id
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "vllm",
                        "deployment-id": deployment_id,
                        "model": _sanitize_k8s_name(config.model_name)
                    }
                },
                "spec": {
                    "containers": [{
                        "name": "vllm",
                        "image": "vllm-cpu-env:latest",
                        "imagePullPolicy": "Never",
                        "args": args,
                        "ports": [{
                            "containerPort": config.port,
                            "name": "http"
                        }],
                        "resources": resources,
                        "env": [
                            {
                                "name": "VLLM_WORKER_MULTIPROC_METHOD",
                                "value": "spawn"
                            },
                            {
                                "name": "CUDA_VISIBLE_DEVICES",
                                "value": ""
                            },
                            {
                                "name": "VLLM_LOGGING_LEVEL",
                                "value": "DEBUG"
                            },
                            {
                                "name": "VLLM_USE_MODELSCOPE",
                                "value": "False"
                            },
                            {
                                "name": "VLLM_TARGET_DEVICE",
                                "value": "cpu"
                            },
                            {
                                "name": "VLLM_CPU_ONLY",
                                "value": "1"
                            },
                            {
                                "name": "VLLM_DISABLE_CUSTOM_ALL_REDUCE",
                                "value": "1"
                            },
                            {
                                "name": "VLLM_PLATFORM",
                                "value": "cpu"
                            },
                            {
                                "name": "VLLM_FORCE_CPU_BACKEND",
                                "value": "1"
                            },
                            {
                                "name": "VLLM_USE_PRECOMPILED",
                                "value": "0"
                            },
                            {
                                "name": "TORCH_CUDA_ARCH_LIST",
                                "value": ""
                            },
                            {
                                "name": "CUDA_LAUNCH_BLOCKING",
                                "value": "1"
                            }
                        ],
                        "readinessProbe": {
                            "httpGet": {
                                "path": "/health",
                                "port": config.port
                            },
                            "initialDelaySeconds": 30,
                            "periodSeconds": 10,
                            "timeoutSeconds": 5,
                            "failureThreshold": 3
                        },
                        "livenessProbe": {
                            "httpGet": {
                                "path": "/health",
                                "port": config.port
                            },
                            "initialDelaySeconds": 60,
                            "periodSeconds": 30,
                            "timeoutSeconds": 10,
                            "failureThreshold": 3
                        }
                    }],
                    "restartPolicy": "Always",
                    "terminationGracePeriodSeconds": 30
                }
            }
        }
    }
    
    return statefulset_template

def create_vllm_deployment_template(
    deployment_name: str,
    config: VLLMConfig,
    deployment_id: str,
    namespace: str = "vllm"
) -> Dict[str, Any]:
    """Create Kubernetes deployment template for vLLM"""
    
    # Build vLLM command arguments
    args = [
        "--model", config.model_name,
        "--gpu-memory-utilization", str(config.gpu_memory_utilization),
        "--max-num-seqs", str(config.max_num_seqs),
        "--block-size", str(config.block_size),
        "--tensor-parallel-size", str(config.tensor_parallel_size),
        "--pipeline-parallel-size", str(config.pipeline_parallel_size),
        "--dtype", config.dtype,
        "--port", str(config.port),
        "--host", config.host,
        "--device", "cpu",  # Force CPU mode for MacBook compatibility
        "--enforce-eager",  # Disable CUDA graph for CPU
        "--disable-custom-all-reduce",  # Disable custom all-reduce for CPU
        "--max-parallel-loading-workers", "1",  # Limit parallel loading
        "--load-format", "auto",  # Auto detect model format
        "--disable-log-stats",  # Reduce logging overhead
        "--disable-log-requests"  # Reduce logging overhead
    ]
    
    if config.trust_remote_code:
        args.append("--trust-remote-code")
    
    if config.max_model_len:
        args.extend(["--max-model-len", str(config.max_model_len)])
    
    if config.quantization:
        args.extend(["--quantization", config.quantization])
    
    if config.served_model_name:
        args.extend(["--served-model-name", config.served_model_name])
    
    # Add additional arguments
    if config.additional_args:
        for key, value in config.additional_args.items():
            if isinstance(value, bool) and value:
                args.append(f"--{key}")
            elif not isinstance(value, bool):
                args.extend([f"--{key}", str(value)])
    
    # Resource requirements based on model size and configuration
    resources = _get_resource_requirements(config)
    
    deployment_template = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": deployment_name,
            "namespace": namespace,
            "labels": {
                "app": "vllm",
                "deployment-id": deployment_id,
                "model": _sanitize_k8s_name(config.model_name)
            }
        },
        "spec": {
            "replicas": 1,
            "selector": {
                "matchLabels": {
                    "app": "vllm",
                    "deployment-id": deployment_id
                }
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": "vllm",
                        "deployment-id": deployment_id,
                        "model": _sanitize_k8s_name(config.model_name)
                    }
                },
                "spec": {
                    "containers": [{
                        "name": "vllm",
                        "image": "vllm-cpu-env:latest",
                        "imagePullPolicy": "Never",
                        "args": args,
                        "ports": [{
                            "containerPort": config.port,
                            "name": "http"
                        }],
                        "resources": resources,
                        "env": [
                            {
                                "name": "VLLM_WORKER_MULTIPROC_METHOD",
                                "value": "spawn"
                            },
                            {
                                "name": "CUDA_VISIBLE_DEVICES",
                                "value": ""
                            },
                            {
                                "name": "VLLM_LOGGING_LEVEL",
                                "value": "DEBUG"
                            },
                            {
                                "name": "VLLM_USE_MODELSCOPE",
                                "value": "False"
                            },
                            {
                                "name": "VLLM_TARGET_DEVICE",
                                "value": "cpu"
                            },
                            {
                                "name": "VLLM_CPU_ONLY",
                                "value": "1"
                            },
                            {
                                "name": "VLLM_DISABLE_CUSTOM_ALL_REDUCE",
                                "value": "1"
                            },
                            {
                                "name": "VLLM_PLATFORM",
                                "value": "cpu"
                            },
                            {
                                "name": "VLLM_FORCE_CPU_BACKEND",
                                "value": "1"
                            },
                            {
                                "name": "VLLM_USE_PRECOMPILED",
                                "value": "0"
                            },
                            {
                                "name": "TORCH_CUDA_ARCH_LIST",
                                "value": ""
                            },
                            {
                                "name": "CUDA_LAUNCH_BLOCKING",
                                "value": "1"
                            }
                        ],
                        "livenessProbe": {
                            "httpGet": {
                                "path": "/health",
                                "port": config.port
                            },
                            "initialDelaySeconds": 180,
                            "periodSeconds": 30,
                            "timeoutSeconds": 10
                        },
                        "readinessProbe": {
                            "httpGet": {
                                "path": "/health",
                                "port": config.port
                            },
                            "initialDelaySeconds": 120,
                            "periodSeconds": 10,
                            "timeoutSeconds": 5
                        }
                    }],
                    "restartPolicy": "Always"
                }
            }
        }
    }
    
    return deployment_template

def create_vllm_service_template(
    service_name: str,
    deployment_id: str,
    port: int,
    namespace: str = "vllm"
) -> Dict[str, Any]:
    """Create Kubernetes service template for vLLM"""
    
    service_template = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": namespace,
            "labels": {
                "app": "vllm",
                "deployment-id": deployment_id
            }
        },
        "spec": {
            "type": "ClusterIP",
            "ports": [{
                "port": port,
                "targetPort": port,
                "protocol": "TCP",
                "name": "http"
            }],
            "selector": {
                "app": "vllm",
                "deployment-id": deployment_id
            }
        }
    }
    
    return service_template

def create_vllm_headless_service_template(
    service_name: str,
    deployment_id: str,
    port: int,
    namespace: str = "vllm"
) -> Dict[str, Any]:
    """Create Kubernetes headless service template for vLLM StatefulSet"""
    
    headless_service_template = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": namespace,
            "labels": {
                "app": "vllm",
                "deployment-id": deployment_id
            }
        },
        "spec": {
            "clusterIP": "None",  # This makes it a headless service
            "ports": [{
                "port": port,
                "targetPort": port,
                "protocol": "TCP",
                "name": "http"
            }],
            "selector": {
                "app": "vllm",
                "deployment-id": deployment_id
            }
        }
    }
    
    return headless_service_template

def _get_resource_requirements(config: VLLMConfig) -> Dict[str, Any]:
    """Get resource requirements based on model configuration"""
    
    # Base resource requirements - CPU 모드에서는 더 많은 메모리 필요
    base_cpu = "4000m"  # CPU 할당량 증가
    base_memory = "16Gi"  # 메모리를 16GB로 대폭 증가
    
    # Adjust based on tensor parallel size
    if config.tensor_parallel_size > 1:
        base_cpu = f"{4000 * config.tensor_parallel_size}m"
        base_memory = f"{16 * config.tensor_parallel_size}Gi"
    
    # Adjust based on max_num_seqs (더 보수적으로 조정)
    if config.max_num_seqs > 64:  # 임계값을 낮춤
        memory_multiplier = max(1.5, config.max_num_seqs / 64)  # 최소 1.5배
        base_memory_value = int(base_memory.replace("Gi", "")) * memory_multiplier
        base_memory = f"{int(base_memory_value)}Gi"
    
    resources = {
        "requests": {
            "cpu": base_cpu,
            "memory": base_memory
        },
        "limits": {
            "cpu": base_cpu,
            "memory": base_memory
        }
    }
    
    # Add GPU resources using the new configuration
    if config.gpu_resource_count > 0 and config.gpu_resource_type != "cpu":
        resources["requests"][config.gpu_resource_type] = str(config.gpu_resource_count)
        resources["limits"][config.gpu_resource_type] = str(config.gpu_resource_count)
    
    return resources

def create_vllm_ingress_template(
    ingress_name: str,
    service_name: str,
    deployment_id: str,
    port: int,
    host: Optional[str] = None,
    namespace: str = "vllm"
) -> Dict[str, Any]:
    """Create Kubernetes ingress template for vLLM (optional)"""
    
    ingress_template = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": ingress_name,
            "namespace": namespace,
            "labels": {
                "app": "vllm",
                "deployment-id": deployment_id
            },
            "annotations": {
                "nginx.ingress.kubernetes.io/rewrite-target": "/",
                "nginx.ingress.kubernetes.io/proxy-body-size": "100m"
            }
        },
        "spec": {
            "rules": [{
                "host": host or f"{deployment_id}.vllm.local",
                "http": {
                    "paths": [{
                        "path": "/",
                        "pathType": "Prefix",
                        "backend": {
                            "service": {
                                "name": service_name,
                                "port": {
                                    "number": port
                                }
                            }
                        }
                    }]
                }
            }]
        }
    }
    
    return ingress_template
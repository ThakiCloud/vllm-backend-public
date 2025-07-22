# Benchmark vLLM Service

FastAPI 기반 vLLM 배포 및 관리 서비스입니다.

## 🎯 주요 기능

- YAML 파일을 통한 vLLM 설정 관리
- Kubernetes 클러스터에 vLLM 서버 배포
- REST API를 통한 vLLM 서버 배포 및 관리
- 실시간 배포 상태 모니터링
- 다중 모델 동시 배포 지원
- vllm 네임스페이스에서 Pod 격리 실행
- **GPU 리소스 충돌 감지 및 자동 해결**
- **동일한 설정의 배포 재사용**
- **MIG GPU 리소스 지원**

## 🚀 로컬 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
export MONGO_URL="mongodb://localhost:27017/?directConnection=true&serverSelectionTimeoutMS=5000&connectTimeoutMS=5000"
export SERVER_PORT=8005
export VLLM_CONFIG_DIR="./configs"
export VLLM_NAMESPACE="vllm"
export KUBECONFIG="/path/to/your/kubeconfig"
```

### 3. 서비스 실행

```bash
python main.py
```

## 🍎 MacBook 환경에서 테스트

MacBook에서 전체 기능을 테스트하려면 로컬 Kubernetes 클러스터가 필요합니다.

### 옵션 1: Docker Desktop with Kubernetes (권장)

1. **Docker Desktop 설치 및 Kubernetes 활성화**
   ```bash
   # Docker Desktop 설치 후 Settings > Kubernetes > Enable Kubernetes 체크
   ```

2. **MongoDB 로컬 실행**
   ```bash
   # Docker로 MongoDB 실행
   docker run -d --name mongodb -p 27017:27017 mongo:latest
   
   # 또는 brew로 설치
   brew install mongodb-community
   brew services start mongodb-community
   ```

3. **가상환경 설정 및 실행**
   ```bash
   # 가상환경 생성 및 활성화
   python -m venv venv
   source venv/bin/activate
   
   # 의존성 설치
   pip install -r requirements.txt
   
   # 환경 변수 설정
   export MONGO_URL="mongodb://localhost:27017/?directConnection=true&serverSelectionTimeoutMS=5000&connectTimeoutMS=5000"
   export SERVER_PORT=8005
   export VLLM_CONFIG_DIR="./configs"
   export VLLM_NAMESPACE="vllm"
   export KUBECONFIG="$HOME/.kube/config"
   
   # 서비스 실행
   python main.py
   ```

4. **Kubernetes 네임스페이스 생성**
   ```bash
   kubectl create namespace vllm
   ```

### 옵션 2: Minikube 사용

1. **Minikube 설치 및 시작**
   ```bash
   # Minikube 설치
   brew install minikube
   
   # Minikube 시작 (GPU 지원 없음)
   minikube start --driver=docker
   
   # Kubernetes 컨텍스트 확인
   kubectl config current-context
   ```

2. **나머지 설정은 옵션 1과 동일**

### 옵션 3: Kind (Kubernetes in Docker) 사용

1. **Kind 설치 및 클러스터 생성**
   ```bash
   # Kind 설치
   brew install kind
   
   # 클러스터 생성
   kind create cluster --name vllm-test
   
   # 컨텍스트 설정
   kubectl cluster-info --context kind-vllm-test
   ```

2. **나머지 설정은 옵션 1과 동일**

### 🧪 MacBook에서 기능 테스트

#### 1. 설정 매칭 테스트 (Kubernetes 없이 가능)
```bash
# 가상환경 활성화
source venv/bin/activate

# 설정 매칭 로직만 테스트
python -c "
import asyncio
from models import VLLMConfig

async def test_config_matching():
    config1 = VLLMConfig(
        model_name='microsoft/DialoGPT-medium',
        gpu_resource_type='nvidia.com/gpu',
        gpu_resource_count=1
    )
    
    config2 = VLLMConfig(
        model_name='microsoft/DialoGPT-medium',
        gpu_resource_type='nvidia.com/gpu',
        gpu_resource_count=1
    )
    
    print(f'Config matching: {config1.matches_config(config2)}')
    print(f'GPU conflict: {config1.conflicts_with_gpu_resources(config2)}')

asyncio.run(test_config_matching())
"
```

#### 2. API 테스트 (MongoDB + Kubernetes 필요)
```bash
# 서비스 실행 후 다른 터미널에서
curl -X POST http://localhost:8005/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "model_name": "microsoft/DialoGPT-medium",
      "gpu_resource_type": "nvidia.com/gpu",
      "gpu_resource_count": 1,
      "port": 8000
    }
  }'
```

#### 3. 배포 상태 확인
```bash
# 배포 목록 확인
curl http://localhost:8005/deployments

# Kubernetes 리소스 확인
kubectl get pods -n vllm
kubectl get deployments -n vllm
kubectl get services -n vllm
```

## 🚀 MacBook 테스트 명령어 모음

### 빠른 테스트 스크립트 사용

```bash
# 실행 권한 부여
chmod +x test_deployment_comparison.sh

# 전체 배포 비교 테스트 실행
./test_deployment_comparison.sh test

# 현재 배포 목록 확인
./test_deployment_comparison.sh list

# 특정 설정으로 배포
./test_deployment_comparison.sh deploy test_scenario1.yaml

# 모든 배포 중지
./test_deployment_comparison.sh stop-all

# 서버 상태 확인
./test_deployment_comparison.sh health

# 도움말 보기
./test_deployment_comparison.sh help
```

### 수동 테스트 명령어

#### 1. 서버 상태 확인
```bash
# 서버 헬스 체크
curl http://localhost:8005/health

# 시스템 상태 확인
curl http://localhost:8005/status

# 설정 파일 목록 확인
curl http://localhost:8005/configs/files
```

#### 2. 배포 비교 테스트 시나리오

**시나리오 1: 첫 번째 배포**
```bash
curl -X POST http://localhost:8005/deploy-from-file \
  -H "Content-Type: application/json" \
  -d '{"config_file": "test_scenario1.yaml"}'
```

**시나리오 2: 동일한 설정으로 재배포 (재사용 테스트)**
```bash
curl -X POST http://localhost:8005/deploy-from-file \
  -H "Content-Type: application/json" \
  -d '{"config_file": "test_scenario2.yaml"}'
```

**시나리오 3: 다른 설정으로 배포 (새 배포)**
```bash
curl -X POST http://localhost:8005/deploy-from-file \
  -H "Content-Type: application/json" \
  -d '{"config_file": "test_scenario3.yaml"}'
```

**시나리오 4: GPU 리소스 충돌 테스트**
```bash
curl -X POST http://localhost:8005/deploy-from-file \
  -H "Content-Type: application/json" \
  -d '{"config_file": "test_gpu_scenario.yaml"}'
```

#### 3. 배포 관리 명령어

**현재 배포 목록 확인**
```bash
curl http://localhost:8005/deployments | jq '.'
```

**특정 배포 상태 확인**
```bash
curl http://localhost:8005/deployments/{deployment_id}/status | jq '.'
```

**배포 중지**
```bash
curl -X DELETE http://localhost:8005/deployments/{deployment_id}
```

#### 4. 직접 설정으로 배포
```bash
# CPU 기반 테스트 배포
curl -X POST http://localhost:8005/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "model_name": "microsoft/DialoGPT-small",
      "gpu_memory_utilization": 0.1,
      "max_num_seqs": 16,
      "gpu_resource_type": "cpu",
      "gpu_resource_count": 0,
      "port": 8000
    }
  }'

# GPU 리소스 테스트 배포
curl -X POST http://localhost:8005/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "model_name": "microsoft/DialoGPT-small",
      "gpu_resource_type": "nvidia.com/gpu",
      "gpu_resource_count": 1,
      "port": 8001
    }
  }'

# MIG 리소스 테스트 배포
curl -X POST http://localhost:8005/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "model_name": "microsoft/DialoGPT-small",
      "gpu_resource_type": "nvidia.com/mig-3g.20gb",
      "gpu_resource_count": 1,
      "port": 8002
    }
  }'
```

#### 5. Kubernetes 리소스 직접 확인
```bash
# vllm 네임스페이스의 모든 리소스 확인
kubectl get all -n vllm

# 배포 상세 정보 확인
kubectl describe deployments -n vllm

# Pod 로그 확인
kubectl logs -l app=vllm -n vllm --tail=50

# 이벤트 확인
kubectl get events -n vllm --sort-by='.lastTimestamp'
```

#### 6. 테스트 결과 분석
```bash
# 배포 비교 결과 확인 (jq 필요)
curl -s http://localhost:8005/deployments | jq '
  to_entries | map({
    deployment_id: .key,
    model: .value.config.model_name,
    gpu_resource: .value.config.gpu_resource_type,
    gpu_count: .value.config.gpu_resource_count,
    status: .value.status,
    created_at: .value.created_at
  })
'

# 간단한 배포 요약
curl -s http://localhost:8005/deployments | jq -r '
  to_entries[] | 
  "\(.key): \(.value.config.model_name) (\(.value.config.gpu_resource_type) x \(.value.config.gpu_resource_count)) - \(.value.status)"
'
```

### 🔍 테스트 포인트

1. **배포 재사용 확인**: 동일한 설정으로 배포 시 기존 배포 재사용 여부
2. **GPU 리소스 충돌 감지**: 같은 GPU 리소스 타입 사용 시 충돌 감지 여부
3. **MIG 리소스 구분**: 다른 MIG 슬라이스 간 독립성 확인
4. **배포 상태 추적**: 배포 생성, 실행, 중지 상태 변화 추적
5. **에러 처리**: 잘못된 설정이나 리소스 부족 시 에러 처리

### ⚠️ MacBook 환경 제한사항

1. **GPU 지원 없음**: MacBook에는 NVIDIA GPU가 없으므로 실제 GPU 워크로드는 실행되지 않습니다.
2. **vLLM 이미지 호환성**: vLLM Docker 이미지가 ARM64 (Apple Silicon)를 지원하지 않을 수 있습니다.
3. **리소스 제한**: 로컬 Kubernetes 클러스터는 제한된 리소스를 가집니다.

### 🔧 MacBook 전용 설정 조정

MacBook에서 테스트할 때는 다음과 같이 설정을 조정하세요:

```yaml
# configs/vllm_config_macos.yaml
model_name: "microsoft/DialoGPT-small"  # 더 작은 모델 사용
gpu_memory_utilization: 0.1  # 낮은 메모리 사용률
max_num_seqs: 16  # 적은 시퀀스 수
tensor_parallel_size: 1
pipeline_parallel_size: 1
gpu_resource_type: "nvidia.com/gpu"  # 테스트용 (실제로는 할당되지 않음)
gpu_resource_count: 1
port: 8000
```

### 🐛 MacBook 환경 트러블슈팅

#### vLLM 이미지 호환성 문제
```bash
# ARM64 호환 이미지 사용 또는 빌드
docker build --platform linux/amd64 -t vllm-test .
```

#### Kubernetes 연결 문제
```bash
# 클러스터 상태 확인
kubectl cluster-info
kubectl get nodes

# 네임스페이스 확인
kubectl get namespaces
kubectl create namespace vllm
```

#### MongoDB 연결 문제
```bash
# MongoDB 상태 확인
docker ps | grep mongo
# 또는
brew services list | grep mongodb

# 연결 테스트
mongosh --host localhost:27017
```

## 📝 API 사용법

### 기본 설정 파일로 vLLM을 vllm 네임스페이스에 배포

```bash
curl -X POST http://localhost:8005/deploy-default
```

### 사용자 정의 설정으로 Kubernetes Pod 배포

```bash
curl -X POST http://localhost:8005/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "model_name": "microsoft/DialoGPT-medium",
      "gpu_memory_utilization": 0.9,
      "max_num_seqs": 256,
      "block_size": 16,
      "port": 8000
    }
  }'
```

### 배포 상태 확인

```bash
curl http://localhost:8005/deployments/{deployment_id}/status
```

### 배포 중지

```bash
curl -X DELETE http://localhost:8005/deployments/{deployment_id}
```

### 배포 정리 (Cleanup)

vllm 네임스페이스에 배포된 모든 리소스를 정리하는 방법:

```bash
# 1. 모든 배포 확인
kubectl get deployments -n vllm
kubectl get services -n vllm
kubectl get pods -n vllm

# 2. 개별 배포 삭제 (API 사용)
curl -X DELETE http://localhost:8005/deployments/{deployment_id}

# 3. 또는 Kubernetes 명령어로 직접 삭제
kubectl delete deployment {deployment_name} -n vllm
kubectl delete service {service_name} -n vllm

# 4. 모든 vLLM 리소스 한번에 삭제
kubectl delete deployments,services -l app=vllm -n vllm

# 5. vllm 네임스페이스 전체 삭제 (주의: 모든 데이터 삭제됨)
kubectl delete namespace vllm

# 6. 실행 중인 로컬 서비스 중지
pkill -f "python.*main.py"
```

### 배포 상태 모니터링

```bash
# Kubernetes 리소스 상태 확인
kubectl get pods -n vllm -w
kubectl logs -f deployment/{deployment_name} -n vllm

# 배포 상세 정보 확인
kubectl describe deployment {deployment_name} -n vllm
kubectl describe pod {pod_name} -n vllm
```

## 🔧 설정 파일 형식

`configs/vllm_config.yaml` 예시:

```yaml
model_name: "microsoft/DialoGPT-medium"
gpu_memory_utilization: 0.9
max_num_seqs: 256
block_size: 16
tensor_parallel_size: 1
pipeline_parallel_size: 1
trust_remote_code: false
dtype: "auto"
port: 8000
host: "0.0.0.0"
# GPU 리소스 설정
gpu_resource_type: "nvidia.com/gpu"
gpu_resource_count: 1
```

### GPU 리소스 타입 예시

```yaml
# 일반 GPU 리소스
gpu_resource_type: "nvidia.com/gpu"
gpu_resource_count: 1

# MIG 3g.20gb 리소스
gpu_resource_type: "nvidia.com/mig-3g.20gb"
gpu_resource_count: 1

# MIG 4g.24gb 리소스
gpu_resource_type: "nvidia.com/mig-4g.24gb"
gpu_resource_count: 1

# 다중 GPU 리소스
gpu_resource_type: "nvidia.com/gpu"
gpu_resource_count: 2
```

## 🎮 GPU 리소스 관리

### 자동 충돌 감지 및 해결

배포 시 다음과 같은 로직이 자동으로 실행됩니다:

1. **기존 배포 확인**: 동일한 모델과 설정으로 실행 중인 배포가 있는지 확인
2. **배포 재사용**: 완전히 일치하는 설정의 배포가 있으면 새로 배포하지 않고 기존 배포 재사용
3. **GPU 리소스 충돌 감지**: 같은 GPU 리소스 타입을 사용하는 다른 배포가 있는지 확인
4. **기존 배포 정리**: 충돌하는 배포가 있으면 자동으로 중지
5. **새 배포 생성**: 충돌이 해결된 후 새로운 배포 생성

### 충돌 감지 규칙

- **일반 GPU**: `nvidia.com/gpu` 리소스를 사용하는 모든 배포는 서로 충돌
- **MIG GPU**: 같은 MIG 슬라이스 타입 (예: `3g.20gb`, `4g.24gb`)을 사용하는 배포는 서로 충돌
- **다른 리소스 타입**: 서로 다른 GPU 리소스 타입은 충돌하지 않음

### 배포 재사용 조건

다음 설정이 모두 일치해야 배포가 재사용됩니다:

- `model_name`: 모델 이름
- `gpu_memory_utilization`: GPU 메모리 사용률
- `max_num_seqs`: 최대 시퀀스 수
- `block_size`: 블록 크기
- `tensor_parallel_size`: 텐서 병렬 크기
- `pipeline_parallel_size`: 파이프라인 병렬 크기
- `trust_remote_code`: 원격 코드 신뢰 여부
- `dtype`: 데이터 타입
- `max_model_len`: 최대 모델 길이
- `quantization`: 양자화 방법
- `served_model_name`: 서빙 모델 이름
- `gpu_resource_type`: GPU 리소스 타입
- `gpu_resource_count`: GPU 리소스 개수
- `additional_args`: 추가 인수

## 🐳 Docker 실행

```bash
# 이미지 빌드
docker build -t benchmark-vllm .

# 컨테이너 실행
docker run -p 8005:8005 -e MONGO_URL="your_mongo_url" benchmark-vllm
```

## ☸️ Kubernetes 배포

```bash
kubectl apply -f benchmark-vllm-deployment.yaml
```

## 📊 모니터링

- Health Check: `GET /health`
- System Status: `GET /status`
- API 문서: `http://localhost:8005/docs`

## 🧹 트러블슈팅 및 정리

### 현재 배포된 vLLM 확인
```bash
# API로 배포 목록 확인
curl http://localhost:8005/deployments

# Kubernetes로 직접 확인
kubectl get pods -n vllm
kubectl get services -n vllm
```

### 문제가 있는 배포 정리
```bash
# 특정 배포 삭제
curl -X DELETE http://localhost:8005/deployments/{deployment_id}

# 응답하지 않는 Pod 강제 삭제
kubectl delete pod {pod_name} -n vllm --force --grace-period=0

# 모든 vLLM 리소스 정리
kubectl delete deployments,services,pods -l app=vllm -n vllm
```

### 완전 초기화
```bash
# 1. 로컬 서비스 중지
pkill -f "python.*main.py"

# 2. vllm 네임스페이스 삭제
kubectl delete namespace vllm

# 3. 네임스페이스 재생성
kubectl create namespace vllm

# 4. 서비스 재시작
python main.py
```
# VLLM Benchmark Backend

VLLM 모델의 벤치마크 실행을 위한 마이크로서비스 기반 백엔드 시스템입니다.

## 🎯 개요

이 시스템은 AI 모델 벤치마킹을 위한 완전한 백엔드 솔루션으로, GitHub에서 벤치마크 설정을 관리하고, Kubernetes에서 벤치마크를 실행하며, 결과를 저장하고 분석할 수 있는 통합 플랫폼입니다.

## 🏗️ 시스템 아키텍처

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │  Benchmark      │    │   GitHub        │
│   (Web UI)      │◄──►│  Manager        │◄──►│   Repository    │
└─────────────────┘    │  (Port: 8001)   │    └─────────────────┘
                       └─────────────────┘              ▲
                                │                       │
                                ▼                       │
┌─────────────────┐    ┌─────────────────┐    ┌─────────┴─────────┐
│  Benchmark      │    │   MongoDB       │    │  MLflow GitHub    │
│  Deployer       │◄──►│   Cluster       │◄──►│  Integration      │
│  (Port: 8002)   │    │  (Port: 27017)  │    │  (Port: 8003)     │
└─────────────────┘    └─────────────────┘    └───────────────────┘
        │                        ▲                       ▲
        ▼                        │                       │
┌─────────────────┐              │              ┌────────┴────────┐
│   Kubernetes    │              │              │    MLflow       │
│   Cluster       │              │              │   Server        │
│        │        │              │              └─────────────────┘
│  ┌───────────┐  │              │
│  │   vLLM    │  │              │
│  │ Service   │  │              │
│  │(Port:8005)│  │              │
│  └───────────┘  │              │
└─────────────────┘              │
        ▲                        │
        │                        │
┌─────────────────┐    ┌─────────┴─────────┐
│  Benchmark      │    │  Benchmark        │
│  Evaluation     │◄──►│  Results          │
│  (Port: 8004)   │    │  (Port: 8000)     │
└─────────────────┘    └───────────────────┘
```

## 📦 마이크로서비스 구성

### 🛠️ [Benchmark Manager](./benchmark-manager/)
- **포트**: 8001
- **역할**: GitHub 레포지토리에서 벤치마크 설정 파일 관리
- **주요 기능**:
  - GitHub 레포지토리 자동 동기화
  - 설정 파일 수정 및 관리
  - 프로젝트별 독립적 설정

### 🚀 [Benchmark Deployer](./benchmark-deployer/)
- **포트**: 8002
- **역할**: Kubernetes 클러스터에서 벤치마크 실행
- **주요 기능**:
  - YAML 기반 Kubernetes 리소스 배포
  - 실시간 로그 모니터링
  - WebSocket 터미널 접근

### 📊 [Benchmark Results](./benchmark-results/)
- **포트**: 8000
- **역할**: 벤치마크 실행 결과 저장 및 조회
- **주요 기능**:
  - 원시/표준화 결과 분리 저장
  - RESTful API 기반 결과 조회
  - 메타데이터 관리

### ⚡ [Benchmark vLLM Service](./benchmark-vllm/)
- **포트**: 8005
- **역할**: Kubernetes 클러스터에서 vLLM 서버 배포 및 관리
- **주요 기능**:
  - YAML 기반 vLLM 서버 배포
  - GPU 리소스 충돌 감지 및 자동 해결
  - 다중 모델 동시 배포 지원
  - 실시간 배포 상태 모니터링

### 🔄 [Benchmark Evaluation Service](./benchmark-eval/)
- **포트**: 8004
- **역할**: vLLM 모델 평가 작업 예약 및 실행
- **주요 기능**:
  - 스케줄링 기반 평가 실행
  - GitHub 템플릿 동적 로딩
  - 백그라운드 작업 처리
  - 배포 서비스와 통합

### 🔗 [MLflow GitHub Integration Service](./benchmark-mlflow/)
- **포트**: 8003
- **역할**: MLflow와 GitHub 레포지토리 자동 동기화
- **주요 기능**:
  - MLflow 모델 버전 폴링
  - GitHub YAML 파일 자동 생성/업데이트
  - 모델 메타데이터 관리
  - 실시간 동기화

### 💾 [MongoDB Cluster](./mongodb/)
- **포트**: 27017
- **역할**: 모든 데이터의 중앙 저장소
- **주요 기능**:
  - 레플리카 셋 기반 고가용성
  - 서비스별 데이터베이스 분리
  - 자동 백업 및 복구

## 🚀 빠른 시작

### 1. 사전 요구사항

```bash
- Docker & Docker Compose
- Kubernetes 클러스터 (minikube, kind, 또는 클라우드)
- kubectl
- GitHub Personal Access Token
```

### 2. 환경 설정

```bash
# 레포지토리 클론
git clone <repository-url>
cd vllm-backend-public

# 환경 변수 설정
export GITHUB_TOKEN="your_github_token_here"
export KUBECONFIG="/path/to/your/kubeconfig"
```

### 3. MongoDB 클러스터 배포

```bash
cd mongodb
kubectl apply -f mongo-secrets.yaml
kubectl apply -f mongo-cluster.yaml
kubectl apply -f mongo.yaml

# 데이터베이스 초기화
kubectl exec -it mongo-0 -- bash /scripts/create-databases.sh
```

### 4. 공유 보안 설정 (필수)

마이크로서비스를 배포하기 전에 공유 보안 정보를 설정해야 합니다:

```bash
# benchmark-shared-secrets.yaml 파일 편집
vi benchmark-shared-secrets.yaml
```

다음 항목들을 설정하세요:

```yaml
stringData:
  # MongoDB 연결 URL (3단계에서 배포한 MongoDB 클러스터)
  MONGO_URL: "mongodb://admin:your-password@mongo-service:27017/?replicaSet=rs0&authSource=admin"
  
  # GitHub Personal Access Token (repo 권한 필요)
  GITHUB_TOKEN: "your_github_personal_access_token_here"
```

**설정 주의사항:**
- `MONGO_URL`: MongoDB Secret에서 설정한 root 비밀번호와 일치해야 함
- `GITHUB_TOKEN`: GitHub Personal Access Token (repo 권한 포함)
- Token 생성: GitHub Settings → Developer settings → Personal access tokens

```bash
# 공유 보안 정보 배포
kubectl apply -f benchmark-shared-secrets.yaml
```

### 5. 마이크로서비스 배포

```bash
# Benchmark Manager 배포
cd benchmark-manager
kubectl apply -f benchmark-manager-deployment.yaml

# Benchmark Deployer 배포
cd ../benchmark-deployer
kubectl apply -f benchmark-deployer-deployment.yaml

# Benchmark Results 배포
cd ../benchmark-results
kubectl apply -f benchmark-results-deployment.yaml

# Benchmark vLLM Service 배포
cd ../benchmark-vllm
kubectl apply -f benchmark-vllm-deployment.yaml

# Benchmark Evaluation Service 배포
cd ../benchmark-eval
kubectl apply -f benchmark-eval-deployment.yaml

# MLflow GitHub Integration Service 배포
cd ../benchmark-mlflow
kubectl apply -f benchmark-mlflow-deployment.yaml
```

### 6. 서비스 확인

```bash
# 모든 서비스 상태 확인
kubectl get pods
kubectl get services

# 포트 포워딩 (로컬 접근용)
kubectl port-forward svc/benchmark-manager-service 8001:8001 &
kubectl port-forward svc/benchmark-deployer-service 8002:8002 &
kubectl port-forward svc/benchmark-results-service 8000:8000 &
kubectl port-forward svc/benchmark-vllm-service 8005:8005 &
kubectl port-forward svc/benchmark-eval-service 8004:8004 &
kubectl port-forward svc/benchmark-mlflow-service 8003:8003 &
```

## 🛠️ 개발 환경 설정

### 로컬 개발 모드

각 서비스를 개별적으로 로컬에서 실행할 수 있습니다:

```bash
# MongoDB 포트 포워딩
kubectl port-forward svc/mongo-service 27017:27017 &

# 환경 변수 설정
export MONGO_URL="mongodb://admin:your-password@localhost:27017/?replicaSet=rs0&authSource=admin"
export GITHUB_TOKEN="your_github_token"

# 각 서비스 실행
cd benchmark-manager && python main.py &
cd benchmark-deployer && python main.py &
cd benchmark-results && python main.py &
cd benchmark-vllm && python main.py &
cd benchmark-eval && python main.py &
cd benchmark-mlflow && python main.py &
```

### Docker Compose 개발 환경

```bash
# docker-compose.yml 생성 후
docker-compose up -d
```

## 📡 API 엔드포인트 요약

### Benchmark Manager (8001)
- `GET /health` - 헬스 체크
- `POST /projects` - 프로젝트 생성
- `GET /projects` - 프로젝트 목록
- `POST /projects/{id}/sync` - 파일 동기화

### Benchmark Deployer (8002)
- `GET /health` - 헬스 체크
- `POST /deploy` - YAML 배포
- `GET /jobs/{job_name}/logs` - 로그 조회
- `WS /terminal/{session_id}` - 터미널 접속

### Benchmark Results (8000)
- `GET /health` - 헬스 체크  
- `POST /raw_input` - 원시 결과 저장
- `POST /standardized_output` - 표준화 결과 저장
- `GET /raw_input` - 결과 목록 조회

### Benchmark vLLM Service (8005)
- `GET /health` - 헬스 체크
- `POST /deploy` - vLLM 서버 배포
- `GET /deployments` - 배포 목록 조회
- `DELETE /deployments/{id}` - 배포 삭제

### Benchmark Evaluation Service (8004)
- `GET /health` - 헬스 체크
- `POST /evaluate` - 평가 작업 예약
- `GET /` - 서비스 상태 확인

### MLflow GitHub Integration Service (8003)
- `GET /health` - 헬스 체크
- `POST /poll` - 수동 폴링 실행
- `GET /connections` - 연결 상태 확인

## 🔧 설정 및 환경 변수

### 공통 환경 변수

```bash
# MongoDB 연결
MONGO_URL="mongodb://admin:your-password@mongo-service:27017/?replicaSet=rs0&authSource=admin"

# GitHub (Manager만 필요)
GITHUB_TOKEN="your_github_personal_access_token"

# Kubernetes (Deployer만 필요)
KUBECONFIG="/path/to/kubeconfig"
```

> **참고**: 실제 운영 환경에서는 이러한 환경 변수들이 `benchmark-shared-secrets.yaml`을 통해 Kubernetes Secret으로 관리됩니다.

### 서비스별 포트

- **Benchmark Manager**: 8001
- **Benchmark Deployer**: 8002  
- **Benchmark Results**: 8000
- **Benchmark vLLM Service**: 8005
- **Benchmark Evaluation Service**: 8004
- **MLflow GitHub Integration Service**: 8003
- **MongoDB**: 27017

## 🔄 워크플로우

### 1. 벤치마크 설정 관리
```
GitHub Repository → Manager → 설정 파일 동기화 → 수정 및 관리
```

### 2. 벤치마크 실행
```
설정 파일 → Deployer → Kubernetes Job 배포 → 실행 모니터링
```

### 3. 결과 수집
```
벤치마크 실행 → Results API → 결과 저장 → 조회 및 분석
```

## 📊 모니터링 및 로그

### 헬스 체크

```bash
# 모든 서비스 헬스 체크
curl http://localhost:8001/health  # Manager
curl http://localhost:8002/health  # Deployer
curl http://localhost:8000/health  # Results
curl http://localhost:8005/health  # vLLM Service
curl http://localhost:8004/health  # Evaluation Service
curl http://localhost:8003/health  # MLflow Integration
```

### 로그 확인

```bash
# Kubernetes 로그
kubectl logs -l app=benchmark-manager
kubectl logs -l app=benchmark-deployer
kubectl logs -l app=benchmark-results
kubectl logs -l app=benchmark-vllm
kubectl logs -l app=benchmark-eval
kubectl logs -l app=benchmark-mlflow
kubectl logs -l app=mongodb
```

## 🔐 보안 고려사항

- **인증**: MongoDB 사용자 인증 활성화
- **권한**: Kubernetes RBAC 기반 접근 제어
- **네트워크**: 서비스 간 내부 통신 암호화
- **시크릿**: GitHub 토큰 등 민감 정보 Kubernetes Secret 관리

## 📚 API 문서

각 서비스의 상세 API 문서는 다음 URL에서 확인할 수 있습니다:

- **Manager**: http://localhost:8001/docs
- **Deployer**: http://localhost:8002/docs  
- **Results**: http://localhost:8000/docs
- **vLLM Service**: http://localhost:8005/docs
- **Evaluation Service**: http://localhost:8004/docs
- **MLflow Integration**: http://localhost:8003/docs

## 🛠️ 트러블슈팅

### 일반적인 문제

1. **MongoDB 연결 실패**
   ```bash
   # MongoDB 상태 확인
   kubectl get pods -l app=mongodb
   kubectl logs mongo-0
   ```

2. **서비스 간 통신 실패**
   ```bash
   # 네트워크 정책 확인
   kubectl get networkpolicies
   kubectl describe svc mongo-service
   ```

3. **Kubernetes 배포 실패**
   ```bash
   # RBAC 권한 확인
   kubectl auth can-i create jobs --as=system:serviceaccount:default:benchmark-deployer
   ```

### 디버깅 모드

```bash
# 상세 로그 활성화
export LOG_LEVEL=DEBUG

# 개별 서비스 디버그 실행
python -m pdb main.py
```

## 🤝 기여

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 📞 지원

- **이슈 리포트**: GitHub Issues
- **문서**: 각 서비스 폴더의 README.md
- **API 문서**: 각 서비스의 `/docs` 엔드포인트

---

**버전**: 1.0.0  
**최종 업데이트**: 2024년  
**개발팀**: VLLM Benchmark Team 

# Benchmark Deployer

Kubernetes 클러스터에서 벤치마크 작업을 배포하고 관리하는 마이크로서비스입니다.

## 🎯 개요

Benchmark Deployer는 YAML 기반의 Kubernetes 리소스 배포, 실시간 로그 모니터링, 그리고 WebSocket 기반의 터미널 접근 기능을 제공하는 서비스입니다. 프론트엔드에서 전송된 YAML 설정을 통해 벤치마크 Job을 배포하고, 실행 상태를 모니터링할 수 있습니다.

## ⭐ 주요 기능

### 📦 배포 관리
- **YAML 배포**: 프론트엔드에서 받은 YAML 문자열을 Kubernetes에 배포
- **리소스 지원**: Job, Deployment, Service, ConfigMap, Secret 등 다양한 리소스
- **네임스페이스 지정**: 원하는 네임스페이스에 리소스 배포
- **안전한 삭제**: 동일한 YAML을 사용한 리소스 삭제

### 📊 모니터링
- **실시간 로그**: 배포된 Job의 로그를 실시간으로 조회
- **상태 확인**: Job 실행 상태 및 시스템 상태 모니터링
- **활성 배포 관리**: 현재 활성화된 배포 목록 관리

### 💻 터미널 접근 (NEW)
- **WebSocket 터미널**: 실제 터미널 세션과 동일한 경험
- **안전한 접근**: 배포된 Job Pod에만 제한적 접근
- **멀티 세션**: 여러 터미널 세션 동시 지원
- **자동 관리**: 세션 타임아웃 및 정리 자동 처리

## 🛠️ 기술 스택

- **Python 3.11**: 메인 언어
- **FastAPI**: 웹 프레임워크
- **Kubernetes Python Client**: Kubernetes API 연동
- **WebSocket**: 실시간 터미널 통신
- **MongoDB**: 배포 상태 저장
- **Docker**: 컨테이너화

## 🚀 설치 및 실행

### 환경 변수 설정

```bash
export MONGO_URL="mongodb://admin:password123@localhost:27017/?replicaSet=rs0&authSource=admin"
export KUBECONFIG="/path/to/kubeconfig"  # Kubernetes 설정 파일
```

### 로컬 실행

```bash
cd benchmark-deployer
pip install -r requirements.txt
python main.py
```

### Docker 실행

```bash
docker build -t benchmark-deployer .
docker run -p 8002:8002 \
  -v ~/.kube:/root/.kube \
  -e MONGO_URL="mongodb://host.docker.internal:27017" \
  benchmark-deployer
```

### Kubernetes 배포

```bash
kubectl apply -f benchmark-deployer-deployment.yaml
```

## 📡 API 엔드포인트

### 배포 관리
- `POST /deploy` - YAML 배포
- `POST /delete` - YAML 삭제  
- `GET /deployments` - 활성 배포 목록

### 작업 관리
- `GET /jobs/{job_name}/status` - Job 상태 조회
- `GET /jobs/{job_name}/logs` - Job 로그 조회
- `POST /jobs/logs` - Job 로그 조회 (상세 옵션)

### 터미널 관리
- `POST /jobs/{job_name}/terminal` - Job 터미널 세션 생성
- `POST /terminal/create` - 터미널 세션 생성 (상세)
- `GET /terminal/sessions` - 터미널 세션 목록
- `DELETE /terminal/{session_id}` - 터미널 세션 종료
- `WS /terminal/{session_id}` - WebSocket 터미널 접속

### 시스템
- `GET /health` - 헬스 체크
- `GET /status` - 시스템 상태

## 💻 터미널 사용 가이드

### 1. 터미널 세션 생성

```bash
# 간단한 방법 (권장)
POST /jobs/{job_name}/terminal?namespace=default&shell=/bin/bash

# 상세 옵션
POST /terminal/create
{
  "job_name": "my-benchmark-job",
  "namespace": "default", 
  "pod_name": "my-benchmark-job-abc123",  // 선택사항
  "container_name": "main",              // 선택사항
  "shell": "/bin/bash"                   // 기본값
}
```

### 2. WebSocket 연결

```javascript
// 세션 생성
const response = await fetch('/jobs/my-job/terminal', { method: 'POST' });
const session = await response.json();

// WebSocket 연결
const ws = new WebSocket(session.websocket_url);

// 메시지 처리
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch(data.type) {
    case 'output':
      terminal.write(data.data);
      break;
    case 'error':
      console.error('터미널 오류:', data.message);
      break;
  }
};

// 명령어 입력
ws.send(JSON.stringify({
  type: 'input',
  data: 'ls -la\n'
}));
```

### 3. 세션 관리

```bash
# 세션 목록 조회
GET /terminal/sessions

# 특정 Job 세션만 조회
GET /terminal/sessions?job_name=my-job

# 세션 종료
DELETE /terminal/{session_id}
DELETE /terminal/job/{job_name}  # Job의 모든 세션
```

## 📄 요청/응답 예시

### 배포 요청

```json
{
  "yaml_content": "apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: test-job\nspec:\n  template:\n    spec:\n      containers:\n      - name: test\n        image: busybox\n        command: ['sh', '-c', 'sleep 3600']\n      restartPolicy: Never",
  "namespace": "default"
}
```

### 터미널 세션 응답

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_name": "test-job",
  "namespace": "default",
  "pod_name": "test-job-abc123",
  "container_name": "test",
  "shell": "/bin/bash",
  "websocket_url": "ws://localhost:8002/terminal/550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-01-01T12:00:00Z"
}
```

## 🏗️ 아키텍처

```
Frontend ─── HTTP ────┐
                      ▼
                 Deployer API
                      │
              ┌───────┼───────┐
              ▼       ▼       ▼
         Kubernetes MongoDB WebSocket
            Cluster  Database Terminal
```

## 📂 파일 구조

```
benchmark-deployer/
├── main.py                     # FastAPI 앱 및 API 엔드포인트
├── config.py                   # 설정값 관리
├── database.py                 # MongoDB 연결
├── models.py                   # Pydantic 모델
├── deployer_manager.py         # 배포 관리 로직
├── kubernetes_client.py        # Kubernetes API 클라이언트
├── terminal_manager.py         # 터미널 세션 관리
├── Dockerfile                  # 컨테이너 빌드
├── benchmark-deployer-deployment.yaml  # K8s 배포 설정
└── requirements.txt            # Python 의존성
```

## 🔧 개발 가이드

### 주요 클래스

- `DeployerManager`: Kubernetes 리소스 배포 및 관리
- `KubernetesClient`: Kubernetes API 통신
- `TerminalManager`: WebSocket 터미널 세션 관리
- `DatabaseManager`: MongoDB 연결 및 상태 저장

### 보안 고려사항

- Job Pod에만 터미널 접근 제한
- 세션 타임아웃 자동 처리
- RBAC 기반 Kubernetes 권한 관리

## 📞 지원

API 문서: http://localhost:8002/docs 
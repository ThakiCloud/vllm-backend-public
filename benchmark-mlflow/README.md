# MLflow GitHub Integration Service

MLflow에서 새로운 모델 버전이 업로드될 때마다 GitHub 레포의 YAML 파일을 자동으로 업데이트하는 폴링 서비스입니다.

## 프로젝트 구조

```
benchmark-mlflow/
├── main.py              # 메인 엔트리 포인트
├── config.py            # 설정 관리
├── models.py            # 데이터 모델 (Pydantic)
├── github_client.py     # GitHub API 클라이언트
├── mlflow_manager.py    # MLflow 폴링 및 관리
├── requirements.txt     # 의존성 라이브러리
└── README.md           # 프로젝트 문서
```

## 기능

- **MLflow 폴링**: MLflow 추적 서버를 주기적으로 폴링하여 새로운 모델 버전 감지
- **GitHub 통합**: 새로운 모델 버전 발견 시 GitHub 레포에 `{run_id}.yaml` 파일 자동 생성/업데이트
- **모델 정보 관리**: `experimentId`, `runid`, `timestamp`, `modelName`, `modelVersion` 필드를 자동 업데이트
- **GitHub 기반 상태 관리**: GitHub 파일 기반으로 중복 처리 방지, JSON 파일 의존성 제거
- **FastAPI 서버**: 수동 폴링 API, 상태 확인 API 제공

## 설치

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

#### 필수 환경 변수

```bash
# MLflow 설정
export MLFLOW_TRACKING_URI=http://localhost:5000
export POLLING_INTERVAL=60

# GitHub 설정 (필수)
export GITHUB_TOKEN=your_github_personal_access_token
export GITHUB_REPO_OWNER=your-github-username
export GITHUB_REPO_NAME=your-repo-name
```

#### 선택적 환경 변수

```bash
# FastAPI 서버 설정
export SERVER_HOST=0.0.0.0
export SERVER_PORT=8003
```

### 3. .env 파일 사용 (권장)

프로젝트 루트에 `.env` 파일을 생성하여 환경 변수를 관리할 수 있습니다:

```env
# MLflow 설정
MLFLOW_TRACKING_URI=http://localhost:5000
POLLING_INTERVAL=60

# GitHub 설정
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_REPO_OWNER=your-github-username
GITHUB_REPO_NAME=your-repo-name

# MongoDB 설정 (선택사항)
MONGODB_HOST=mongodb-service
MONGODB_PORT=27017
MONGODB_DB=benchmark_mlflow
MONGODB_USER=admin
MONGODB_PASSWORD=password123
MONGODB_REPLICA_SET=rs0
MONGODB_AUTH_SOURCE=admin
```

## GitHub 토큰 설정

GitHub Personal Access Token을 생성하고 다음 권한을 부여해야 합니다:

1. **Settings** > **Developer settings** > **Personal access tokens** > **Tokens (classic)** 선택
2. **Generate new token** 클릭
3. 다음 권한 선택:
   - `repo` - 레포지토리 읽기/쓰기 권한
   - `contents:write` - 파일 컨텐츠 수정 권한

## 사용법

### 기본 실행

```bash
python main.py
```

### Docker 실행 (선택사항)

```bash
# Dockerfile 생성 후
docker build -t mlflow-github-integration .
docker run -d --env-file .env mlflow-github-integration
```

## 모듈 설명

### main.py
- 서비스의 메인 엔트리 포인트
- 설정 로드 및 연결 테스트
- MLflowManager 초기화 및 폴링 시작

### config.py
- 환경 변수 기반 설정 관리
- GitHub 및 PostgreSQL 설정 검증
- 기본값 및 상수 정의

### models.py
- Pydantic 기반 데이터 모델
- MLflow 이벤트, GitHub 설정, 데이터베이스 설정 등
- 타입 안전성 및 데이터 검증

### github_client.py
- GitHub API 클라이언트
- run_id별 YAML 파일 생성/업데이트
- 연결 테스트 및 저장소 정보 조회

### mlflow_manager.py
- MLflow 폴링 및 이벤트 관리
- 새로운 모델/버전 감지
- MongoDB 이벤트 저장 및 상태 관리

## YAML 파일 구조

서비스는 각 run_id마다 개별 YAML 파일을 생성/업데이트합니다:

```yaml
# {run_id}.yaml 예시 (예: abc123def456.yaml)
global:
  experimentId: "1"
  runid: abc123def456
  timestamp: 20240101
vllm:
  vllm:
    model: "/mlflow/{{ .Values.global.experimentId }}/{{ .Values.global.runid }}/artifacts/model"
    maxModelLen: 4096
    gpuMemoryUtilization: 0.9
    trust_remote_code: true
    served_model_name: "Qwen/Qwen3-0.6B"
  # ... 기타 Kubernetes 배포 설정
```

각 새로운 MLflow 실행마다 해당 run_id 이름의 YAML 파일이 자동으로 생성됩니다. 새로운 run_id의 경우 전체 Kubernetes 배포 템플릿이 생성되고, 기존 run_id의 경우 global 섹션의 timestamp만 업데이트됩니다.

## 동작 방식

1. **초기화**: 설정 로드 및 연결 테스트
2. **FastAPI 서버 시작**: 백그라운드 폴링 및 수동 API 제공
3. **폴링 루프**:
   - MLflow 서버에서 새로운 모델/버전 감지
   - GitHub 파일 기반으로 중복 체크 (기존 YAML 파일 존재 여부)
   - run_id에서 experiment_id 동적 조회
   - GitHub 레포에 `{run_id}.yaml` 파일 생성/업데이트
   - 상태는 GitHub 파일 자체로 관리

## 로그 예시

```
2024-01-01 12:00:00 - __main__ - INFO - MLflow GitHub Integration Service 시작
2024-01-01 12:00:01 - __main__ - INFO - GitHub 설정 로드 완료: username/repo-name
2024-01-01 12:00:02 - __main__ - INFO - mlflow: 연결 성공
2024-01-01 12:00:03 - __main__ - INFO - github: 연결 성공
2024-01-01 12:00:04 - mlflow_manager - INFO - 새로운 모델 버전 감지: my_model:1
2024-01-01 12:00:05 - github_client - INFO - GitHub 레포의 abc123def456.yaml 업데이트 완료: experimentId=1, runid=abc123def456
2024-01-01 12:00:06 - mlflow_manager - INFO - 폴링 완료: 1개 이벤트, 1개 GitHub 업데이트 성공
```

## 상태 관리

- **GitHub 파일 기반**: GitHub 레포의 YAML 파일들이 상태 정보 역할
- **중복 방지**: 기존 `{run_id}.yaml` 파일 존재 여부로 중복 체크
- **실시간 동기화**: 파일 내용의 `modelName`, `modelVersion` 비교로 변경사항 감지
- **JSON 파일 불필요**: 로컬 상태 파일 제거로 단순화

## 오류 처리

- **GitHub API 오류**: 로그 출력 후 다음 폴링 계속
- **MLflow 연결 오류**: 로그 출력 후 재시도
- **YAML 파일 생성 오류**: 로그 출력 후 해당 run_id 건너뛰기
- **파일 파싱 오류**: 기존 YAML 파일 손상 시 새로 생성

## 개발 및 확장

### 새로운 기능 추가

1. `models.py`에 새로운 데이터 모델 추가
2. 해당 기능을 담당하는 별도 모듈 생성
3. `main.py`에서 새로운 모듈 통합

### 테스트

```bash
# FastAPI 서버 실행 (개발 모드)
uvicorn main:app --host 0.0.0.0 --port 8003 --reload

# 수동 폴링 API 호출
curl -X POST http://localhost:8003/poll

# 연결 상태 확인
curl http://localhost:8003/connections

# Health check
curl http://localhost:8003/health

# API 문서 확인
curl http://localhost:8003/docs
```

## 문제 해결

### 일반적인 문제

1. **GitHub 인증 오류**: 토큰 권한 확인
2. **MLflow 연결 오류**: 서버 상태 및 URI 확인
3. **YAML 파일 오류**: GitHub 레포 권한 및 파일 생성 권한 확인
4. **FastAPI 서버 오류**: 포트 충돌 또는 환경변수 설정 확인

### 디버깅

로그 레벨을 DEBUG로 변경하여 상세 정보 확인:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
``` 
# Benchmark Manager

GitHub 레포지토리에서 벤치마크 설정 파일을 관리하는 FastAPI 기반 백엔드 서비스입니다.

## 🎯 개요

여러 GitHub 레포지토리에서 벤치마크 설정 파일들을 자동으로 동기화하고, 웹에서 이를 수정할 수 있도록 하는 관리 도구입니다. 원본 파일은 GitHub에서 가져오고, 사용자 수정사항은 별도로 관리하여 원본과 수정본을 분리 저장합니다.

## ⭐ 주요 기능

### 📁 프로젝트 관리
- **GitHub 연동**: 레포지토리 URL과 토큰으로 프로젝트 생성
- **개별 설정**: 프로젝트별 독립적인 config/job 폴더 경로 설정
- **자동 폴링**: 설정 간격으로 GitHub에서 최신 파일 자동 동기화

### 📄 파일 동기화  
- **원본 보존**: GitHub 원본 파일 자동 폴링 및 저장
- **형식 지원**: YAML, JSON 설정 파일 및 YAML job 파일
- **수동 새로고침**: 필요시 즉시 동기화 실행

### ✏️ 수정 관리
- **분리 저장**: 원본과 수정본 독립적 관리
- **파일명 변경**: 수정 파일 이름 변경 가능 (원본 연관성 유지)
- **선택적 삭제**: 개별 수정 파일 삭제
- **프로젝트 초기화**: 모든 수정본 삭제, 원본만 유지

## 🛠️ 기술 스택

- **Python 3.11**: 메인 언어
- **FastAPI**: 웹 프레임워크  
- **MongoDB**: 데이터베이스
- **GitHub API**: 파일 동기화
- **APScheduler**: 백그라운드 폴링

## 🚀 설치 및 실행

### 환경 변수 설정

```bash
export MONGO_URL="mongodb://admin:password123@localhost:27017/?replicaSet=rs0&authSource=admin"
export GITHUB_TOKEN="your_github_token_here"
```

### 로컬 실행

```bash
cd benchmark-manager
pip install -r requirements.txt
python main.py
```

### Docker 실행

```bash
docker build -t benchmark-manager .
docker run -p 8001:8001 \
  -e MONGO_URL="mongodb://host.docker.internal:27017" \
  -e GITHUB_TOKEN="your_token" \
  benchmark-manager
```

### Kubernetes 배포

```bash
kubectl apply -f benchmark-manager-deployment.yaml
```

## 📡 API 엔드포인트

### 시스템 상태
- `GET /health` - 헬스 체크
- `GET /status` - 시스템 상태 및 통계

### 프로젝트 관리
- `POST /projects` - 프로젝트 생성
- `GET /projects` - 프로젝트 목록 조회
- `GET /projects/{project_id}` - 프로젝트 상세 조회
- `PUT /projects/{project_id}` - 프로젝트 수정
- `DELETE /projects/{project_id}` - 프로젝트 삭제

### 파일 동기화
- `POST /projects/{project_id}/sync` - 수동 파일 동기화
- `GET /projects/{project_id}/files` - 프로젝트 파일 목록
- `GET /projects/{project_id}/files/{file_id}` - 파일 상세 정보

### 수정 파일 관리
- `POST /projects/{project_id}/modified-files` - 수정 파일 생성
- `GET /projects/{project_id}/modified-files` - 수정 파일 목록
- `GET /modified-files/{modified_file_id}` - 수정 파일 상세
- `PUT /modified-files/{modified_file_id}` - 수정 파일 업데이트
- `DELETE /modified-files/{modified_file_id}` - 수정 파일 삭제
- `DELETE /projects/{project_id}/modified-files` - 프로젝트 초기화

## 🛠️ 사용 예시

### 1. 프로젝트 생성

```bash
curl -X POST "http://localhost:8001/projects" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "VLLM Benchmark",
    "github_repo_url": "https://api.github.com/repos/owner/repo",
    "github_token": "ghp_xxxxxxxxxxxxxxxxxxxx",
    "config_folder": "config",
    "job_folder": "job", 
    "polling_interval": 180
  }'
```

### 2. 파일 동기화

```bash
curl -X POST "http://localhost:8001/projects/{project_id}/sync"
```

### 3. 수정 파일 생성

```bash
curl -X POST "http://localhost:8001/projects/{project_id}/modified-files" \
  -H "Content-Type: application/json" \
  -d '{
    "original_file_id": "original_file_id_here",
    "modified_name": "custom-config.yaml",
    "content": "modified yaml content here..."
  }'
```

## 🏗️ 아키텍처

```
Frontend ────── HTTP ──────── Manager API
                                   │
                        ┌──────────┼──────────┐
                        ▼          ▼          ▼
                   GitHub API  MongoDB   Scheduler
                     (Sync)   (Storage)  (Polling)
```

## 📂 파일 구조

```
benchmark-manager/
├── main.py                     # FastAPI 앱 및 API 엔드포인트
├── config.py                   # 설정값 관리
├── database.py                 # MongoDB 연결
├── models.py                   # Pydantic 모델
├── github_client.py            # GitHub API 클라이언트
├── project_manager.py          # 프로젝트 관리 및 폴링
├── file_manager.py             # 파일 수정 관리
├── Dockerfile                  # 컨테이너 빌드
├── benchmark-manager-deployment.yaml  # K8s 배포 설정
└── requirements.txt            # Python 의존성
```

## 💾 데이터베이스 스키마

### 프로젝트 컬렉션
- `name`: 프로젝트 이름
- `github_repo_url`: GitHub API URL
- `github_token`: 인증 토큰
- `config_folder`: 설정 파일 폴더
- `job_folder`: Job 파일 폴더
- `polling_interval`: 폴링 간격(초)

### 파일 컬렉션
- `project_id`: 프로젝트 ID
- `name`: 파일명
- `path`: 파일 경로  
- `content`: 파일 내용
- `file_type`: config/job
- `last_modified`: 최종 수정일

### 수정 파일 컬렉션
- `original_file_id`: 원본 파일 ID
- `modified_name`: 수정된 파일명
- `content`: 수정된 내용
- `created_at`: 생성일

## 📞 지원

API 문서: http://localhost:8001/docs 
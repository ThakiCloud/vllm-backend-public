# Benchmark Results

벤치마크 실행 결과를 저장하고 조회하는 FastAPI 기반 백엔드 서비스입니다.

## 🎯 개요

AI 모델 벤치마크 실행 결과를 중앙 집중식으로 수집, 저장, 조회하는 서비스입니다. 원시 결과(raw_input)와 표준화된 결과(standardized_output)를 구분하여 저장하며, 풍부한 메타데이터와 함께 결과를 관리합니다.

## ⭐ 주요 기능

### 📊 결과 저장
- **원시 결과**: 가공되지 않은 벤치마크 원본 데이터 저장
- **표준화 결과**: 파싱/가공된 표준 형식의 데이터 저장  
- **JSON 검증**: 자동 JSON 파싱 및 데이터 유효성 검증
- **중복 방지**: 고유 키 기반 중복 저장 방지

### 🔍 결과 조회
- **목록 조회**: 저장된 결과 목록 조회 (메타데이터 포함)
- **상세 조회**: 특정 결과의 전체 데이터 조회
- **타입별 분리**: raw/standardized 결과 별도 조회

### 🛠️ 시스템 관리
- **헬스 체크**: API 및 MongoDB 연결 상태 모니터링
- **자동 인덱스**: 검색 성능 최적화를 위한 인덱스 관리
- **모듈화 설계**: 관심사 분리를 통한 유지보수성 향상

## 🛠️ 기술 스택

- **Python 3.11**: 메인 언어
- **FastAPI**: 웹 프레임워크
- **MongoDB**: NoSQL 데이터베이스
- **Pydantic**: 데이터 검증 및 직렬화

## 🚀 설치 및 실행

### 환경 변수 설정

```bash
export MONGO_URL="mongodb://admin:password123@localhost:27017/?replicaSet=rs0&authSource=admin"
```

### 로컬 실행

```bash
cd benchmark-results
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker 실행

```bash
docker build -t benchmark-results .
docker run -p 8000:8000 \
  -e MONGO_URL="mongodb://host.docker.internal:27017" \
  benchmark-results
```

### Kubernetes 배포

```bash
kubectl apply -f benchmark-results-deployment.yaml
```

## 📡 API 엔드포인트

### 시스템 상태
- `GET /health` - 헬스 체크 및 MongoDB 연결 상태

### 원시 결과 관리
- `POST /raw_input` - 원시 벤치마크 결과 저장
- `GET /raw_input` - 원시 결과 목록 조회
- `GET /raw_input/{result_name}` - 특정 원시 결과 조회

### 표준화 결과 관리
- `POST /standardized_output` - 표준화된 벤치마크 결과 저장
- `GET /standardized_output` - 표준화 결과 목록 조회
- `GET /standardized_output/{result_name}` - 특정 표준화 결과 조회

## 🛠️ 사용 예시

### 1. 원시 결과 저장

```bash
curl -X POST "http://localhost:8000/raw_input" \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "test-run-001",
    "benchmark_name": "mmlu",
    "data": {
      "accuracy": 0.85,
      "total_questions": 1000,
      "correct_answers": 850
    },
    "timestamp": "2024-01-01T12:00:00Z",
    "model_id": "gpt-4",
    "tokenizer_id": "gpt-4-tokenizer",
    "source": "evaluation-pipeline"
  }'
```

### 2. 결과 목록 조회

```bash
curl "http://localhost:8000/raw_input"
```

### 3. 특정 결과 조회

```bash
curl "http://localhost:8000/raw_input/2024-01-01T12:00:00Z-mmlu-test-run-001"
```

### 4. 표준화 결과 저장

```bash
curl -X POST "http://localhost:8000/standardized_output" \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "test-run-001", 
    "benchmark_name": "mmlu",
    "data": {
      "score": 0.85,
      "category": "language_understanding",
      "rank": "A"
    },
    "timestamp": "2024-01-01T12:05:00Z",
    "model_id": "gpt-4",
    "source": "processing-pipeline"
  }'
```

## 🏗️ 아키텍처

```
Benchmark Runners ──── HTTP ──── Results API ──── MongoDB
    (외부 실행기)                     (FastAPI)       (Database)
                                        │
                                        ▼
                                   Web Frontend
                                   (결과 조회)
```

## 📂 파일 구조

```
benchmark-results/
├── main.py                     # FastAPI 앱 및 API 엔드포인트
├── config.py                   # 설정값 관리
├── database.py                 # MongoDB 연결 및 관리
├── models.py                   # Pydantic 모델 정의
├── results_manager.py          # 결과 저장/조회 비즈니스 로직
├── Dockerfile                  # 컨테이너 빌드
├── benchmark-results-deployment.yaml  # K8s 배포 설정
└── requirements.txt            # Python 의존성
```

## 💾 데이터 모델

### 벤치마크 결과 (공통)
- `run_id`: 실행 ID
- `benchmark_name`: 벤치마크 이름  
- `data`: 결과 데이터 (JSON)
- `timestamp`: 타임스탬프
- `model_id`: 모델 ID
- `tokenizer_id`: 토크나이저 ID (선택)
- `source`: 결과 생성 소스

### 고유 키 생성
결과는 `timestamp-benchmark_name-run_id` 형식의 고유 키로 관리됩니다.

## 📞 지원

API 문서: http://localhost:8000/docs 
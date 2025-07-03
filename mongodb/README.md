# MongoDB 클러스터

벤치마크 시스템을 위한 MongoDB 레플리카 셋 클러스터 설정입니다.

## 🎯 개요

VLLM 벤치마크 시스템의 모든 데이터를 저장하는 MongoDB 클러스터입니다. 레플리카 셋으로 구성되어 고가용성과 데이터 일관성을 보장합니다.

## ⭐ 주요 기능

### 🏗️ 레플리카 셋 구성
- **고가용성**: Primary-Secondary 구조로 자동 장애 조치
- **데이터 복제**: 여러 노드에 데이터 자동 복제
- **읽기 분산**: Secondary 노드를 통한 읽기 부하 분산

### 🔐 보안 설정
- **인증 활성화**: 사용자 인증 기반 접근 제어
- **TLS 암호화**: 네트워크 통신 암호화 (선택)
- **역할 기반 접근**: 서비스별 전용 사용자 계정

### 💾 데이터 저장소
- **프로젝트 관리**: benchmark-manager 데이터
- **배포 상태**: benchmark-deployer 데이터  
- **결과 저장**: benchmark-results 데이터

## 🚀 배포 및 설정

### Kubernetes 배포

```bash
# Secret 생성 (비밀번호 설정)
kubectl apply -f mongo-secrets.yaml

# MongoDB 클러스터 배포
kubectl apply -f mongo-cluster.yaml

# 서비스 노출
kubectl apply -f mongo.yaml
```

### 데이터베이스 초기화

```bash
# 초기 데이터베이스 및 사용자 생성
kubectl exec -it mongodb-0 -- bash /scripts/create-databases.sh

# 데이터베이스 리셋 (개발용)
kubectl exec -it mongodb-0 -- bash /scripts/reset-databases.sh
```

## 📂 파일 구조

```
mongodb/
├── mongo-cluster.yaml          # MongoDB StatefulSet 및 서비스
├── mongo.yaml                  # 외부 서비스 노출
├── mongo-secrets.yaml          # 인증 정보 (Secret)
├── create-databases.sh         # 데이터베이스 초기화 스크립트
├── reset-databases.sh          # 데이터베이스 리셋 스크립트
└── README.md                   # 이 파일
```

## 🔧 구성 요소

### StatefulSet (mongo-cluster.yaml)
- **mongodb-0**: Primary 노드
- **mongodb-1**: Secondary 노드  
- **mongodb-2**: Secondary 노드
- **영구 저장소**: 각 노드당 10Gi PVC

### 서비스 (mongo.yaml)
- **mongodb-service**: 내부 클러스터 접근 (포트 27017)
- **LoadBalancer**: 외부 접근 가능 (선택사항)

### 보안 (mongo-secrets.yaml)
- **Root 사용자**: 관리자 계정
- **앱 사용자**: 애플리케이션별 전용 계정

## 🔌 연결 정보

### 내부 서비스 연결 (Kubernetes 내부)

```bash
mongodb://admin:password123@mongodb-service:27017/?replicaSet=rs0&authSource=admin
```

### 외부 연결 (LoadBalancer 사용시)

```bash
mongodb://admin:password123@<EXTERNAL-IP>:27017/?replicaSet=rs0&authSource=admin
```

### 애플리케이션별 연결 문자열

```bash
# benchmark-manager
mongodb://manager-user:manager-pass@mongodb-service:27017/benchmark_manager?replicaSet=rs0&authSource=benchmark_manager

# benchmark-deployer  
mongodb://deployer-user:deployer-pass@mongodb-service:27017/benchmark_deployer?replicaSet=rs0&authSource=benchmark_deployer

# benchmark-results
mongodb://results-user:results-pass@mongodb-service:27017/benchmark_results?replicaSet=rs0&authSource=benchmark_results
```

## 💾 데이터베이스 구조

### benchmark_manager
- `projects`: 프로젝트 정보
- `files`: GitHub에서 동기화된 파일
- `modified_files`: 사용자 수정 파일

### benchmark_deployer  
- `deployments`: Kubernetes 배포 상태
- `terminal_sessions`: 터미널 세션 정보

### benchmark_results
- `raw_input`: 원시 벤치마크 결과
- `standardized_output`: 표준화된 결과

## 🛠️ 관리 명령어

### 클러스터 상태 확인

```bash
kubectl get pods -l app=mongodb
kubectl get pvc -l app=mongodb
kubectl logs mongodb-0
```

### 레플리카 셋 상태 확인

```bash
kubectl exec -it mongodb-0 -- mongosh --eval "rs.status()"
```

### 데이터베이스 목록 확인

```bash
kubectl exec -it mongodb-0 -- mongosh -u admin -p password123 --eval "show dbs"
```

### 백업 및 복원

```bash
# 백업
kubectl exec -it mongodb-0 -- mongodump --uri="mongodb://admin:password123@localhost:27017/?authSource=admin" --out /backup

# 복원
kubectl exec -it mongodb-0 -- mongorestore --uri="mongodb://admin:password123@localhost:27017/?authSource=admin" /backup
```

## 🔧 트러블슈팅

### 일반적인 문제

1. **Pod가 시작되지 않음**
   - PVC 상태 확인: `kubectl get pvc`
   - 스토리지 클래스 확인: `kubectl get storageclass`

2. **레플리카 셋 초기화 실패**
   - 네트워크 정책 확인
   - DNS 해상도 확인: `nslookup mongodb-service`

3. **연결 실패**
   - 인증 정보 확인
   - 방화벽 및 네트워크 정책 확인

### 로그 확인

```bash
# MongoDB 로그
kubectl logs mongodb-0

# 초기화 스크립트 로그
kubectl logs mongodb-0 -c mongo-init
```

## 📞 지원

MongoDB 관리에 대한 문의사항이 있으시면 시스템 관리자에게 연락하세요. 
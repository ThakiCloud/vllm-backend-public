#!/bin/bash

echo "🗑️  MongoDB 데이터베이스 삭제 스크립트"
echo "⚠️  경고: 이 스크립트는 모든 benchmark 관련 데이터베이스를 완전히 삭제합니다!"
echo "     - manage_db (benchmark-manager)"
echo "     - deploy_db (benchmark-deployer)"
echo "     - result_db (benchmark-results)"
echo ""

# 확인 메시지
read -p "정말로 모든 데이터베이스를 삭제하시겠습니까? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "❌ 취소되었습니다."
    exit 1
fi

echo "🔍 MongoDB pod 상태 확인 중..."

# Wait for MongoDB pod to be ready
echo "MongoDB pod가 준비될 때까지 기다리는 중..."
until kubectl get pod mongo-0 &>/dev/null && kubectl get pod mongo-0 -o jsonpath='{.status.phase}' | grep -q "Running"; do
  echo "mongo-0 pod 대기 중..."
  sleep 5
done

echo "✅ MongoDB pod가 준비되었습니다!"

# Get MongoDB credentials from secret
echo "🔐 MongoDB 인증 정보 가져오는 중..."
MONGO_PASSWORD=$(kubectl get secret mongo-secret -o jsonpath='{.data.mongodb-root-password}' | base64 -d)

echo "인증 정보:"
echo "MONGO_USERNAME: admin"
echo "MONGO_PASSWORD: $MONGO_PASSWORD"

# Delete databases using kubectl exec with URI connection
echo ""
echo "🗑️  데이터베이스 삭제 시작..."

kubectl exec mongo-0 -- mongosh "mongodb://admin:$MONGO_PASSWORD@localhost:27017/admin" --eval "
// 현재 데이터베이스 목록 출력
print('=== 삭제 전 데이터베이스 목록 ===');
db.adminCommand('listDatabases').databases.forEach(function(database) {
  print('📁 ' + database.name + ' (' + (database.sizeOnDisk / 1024 / 1024).toFixed(2) + ' MB)');
});

print('');
print('🗑️  데이터베이스 삭제 중...');

// manage_db 삭제 (benchmark-manager)
try {
  var manageDb = db.getSiblingDB('manage_db');
  var result = manageDb.dropDatabase();
  if (result.ok) {
    print('✅ manage_db 삭제 완료');
  } else {
    print('❌ manage_db 삭제 실패');
  }
  manageDb.createCollection('temp');
} catch (e) {
  print('⚠️  manage_db 삭제 중 오류: ' + e.message);
}

// deploy_db 삭제 (benchmark-deployer)
try {
  var deployDb = db.getSiblingDB('deploy_db');
  var result = deployDb.dropDatabase();
  if (result.ok) {
    print('✅ deploy_db 삭제 완료');
  } else {
    print('❌ deploy_db 삭제 실패');
  }
  deployDb.createCollection('temp');
} catch (e) {
  print('⚠️  deploy_db 삭제 중 오류: ' + e.message);
}

// result_db 삭제 (benchmark-results)
try {
  var resultDb = db.getSiblingDB('result_db');
  var result = resultDb.dropDatabase();
  if (result.ok) {
    print('✅ result_db 삭제 완료');
  } else {
    print('❌ result_db 삭제 실패');
  }
  resultDb.createCollection('temp');
} catch (e) {
  print('⚠️  result_db 삭제 중 오류: ' + e.message);
}

print('');
print('=== 삭제 후 데이터베이스 목록 ===');
db.adminCommand('listDatabases').databases.forEach(function(database) {
  print('📁 ' + database.name + ' (' + (database.sizeOnDisk / 1024 / 1024).toFixed(2) + ' MB)');
});

print('');
print('🎉 데이터베이스 삭제 작업 완료!');
print('💡 애플리케이션을 재시작하면 새로운 인덱스로 데이터베이스가 다시 생성됩니다.');
"

echo ""
echo "✨ 데이터베이스 삭제 완료!"
echo "💡 이제 애플리케이션을 재시작하면:"
echo "   - 새로운 sparse 인덱스로 데이터베이스가 생성됩니다"
echo "   - E11000 duplicate key error 문제가 해결됩니다"
echo ""
echo "🚀 애플리케이션 재시작 명령어:"
echo "   kubectl rollout restart deployment benchmark-manager"
echo "   kubectl rollout restart deployment benchmark-deployer"
echo "   kubectl rollout restart deployment benchmark-results" 
#!/bin/bash

echo "Creating MongoDB databases in Kubernetes cluster..."

# Wait for MongoDB pod to be ready
echo "Waiting for MongoDB pod to be ready..."
until kubectl get pod mongo-0 &>/dev/null && kubectl get pod mongo-0 -o jsonpath='{.status.phase}' | grep -q "Running"; do
  echo "Waiting for mongo-0 pod..."
  sleep 5
done

echo "MongoDB pod is ready! Getting credentials..."

# Get MongoDB credentials from secret
MONGO_PASSWORD=$(kubectl get secret mongo-secret -o jsonpath='{.data.mongodb-root-password}' | base64 -d)

echo "Connecting with authentication..."
echo "MONGO_USERNAME: admin"
echo "MONGO_PASSWORD: $MONGO_PASSWORD"

# Create databases using kubectl exec with URI connection
kubectl exec mongo-0 -- mongosh "mongodb://admin:$MONGO_PASSWORD@localhost:27017/admin" --eval "
// Show current databases
print('Current databases:');
db.adminCommand('listDatabases').databases.forEach(function(database) {
  print(database.name);
});

// Create manage_db database
print('Creating manage_db...');
var manageDb = db.getSiblingDB('deployments');
manageDb.createCollection('temp');
print('✓ manage_db created');

// Show updated databases
print('Updated databases:');
db.adminCommand('listDatabases').databases.forEach(function(database) {
  print(database.name);
});
"

echo "Database creation completed!"
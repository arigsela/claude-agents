#!/bin/bash
# Restore Qdrant data from backup
#
# Usage:
#   Local Docker: ./scripts/restore-qdrant.sh docker ./backups/qdrant-backup-YYYYMMDD.tar.gz
#   Kubernetes:   ./scripts/restore-qdrant.sh k8s ./backups/snapshot-name.snapshot
#
# WARNING: This will overwrite existing data!

set -e

MODE="${1:-docker}"
BACKUP_FILE="${2}"

if [ -z "${BACKUP_FILE}" ]; then
  echo "Usage: $0 [docker|k8s] <backup-file>"
  echo ""
  echo "Available backups:"
  ls -la ./backups/ 2>/dev/null || echo "No backups found in ./backups/"
  exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "Error: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

case "${MODE}" in
  docker)
    echo "Restoring Qdrant to Docker volume..."
    echo "WARNING: This will stop the container and overwrite existing data!"
    read -p "Continue? (y/N) " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Aborted."
      exit 0
    fi

    # Stop container if running
    docker stop rag-mcp-qdrant 2>/dev/null || true

    # Clear existing data and restore
    docker run --rm \
      -v rag-mcp-server_qdrant_storage:/data \
      -v "$(pwd)":/backup \
      alpine:latest \
      sh -c "rm -rf /data/* && tar xzf /backup/${BACKUP_FILE} -C /data"

    # Start container
    docker start rag-mcp-qdrant 2>/dev/null || echo "Container not found, run 'docker compose up -d' to start"

    echo "Restore complete!"
    ;;

  k8s|kubernetes)
    echo "Restoring Qdrant to Kubernetes..."

    NAMESPACE="${QDRANT_NAMESPACE:-rag-mcp}"
    POD=$(kubectl get pods -n "${NAMESPACE}" -l app=qdrant -o jsonpath='{.items[0].metadata.name}')

    if [ -z "${POD}" ]; then
      echo "Error: No Qdrant pod found in namespace ${NAMESPACE}"
      exit 1
    fi

    echo "Found pod: ${POD}"
    echo "WARNING: This will overwrite existing data!"
    read -p "Continue? (y/N) " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Aborted."
      exit 0
    fi

    # Copy snapshot to pod
    SNAPSHOT_NAME=$(basename "${BACKUP_FILE}")
    kubectl cp "${BACKUP_FILE}" "${NAMESPACE}/${POD}:/qdrant/storage/snapshots/${SNAPSHOT_NAME}"

    # Recover from snapshot via API
    echo "Recovering from snapshot..."
    kubectl exec -n "${NAMESPACE}" "${POD}" -- \
      wget -q -O - --post-data="{\"location\": \"/qdrant/storage/snapshots/${SNAPSHOT_NAME}\"}" \
      --header="Content-Type: application/json" \
      'http://localhost:6333/snapshots/recover'

    echo "Restore complete!"
    ;;

  *)
    echo "Usage: $0 [docker|k8s] <backup-file>"
    exit 1
    ;;
esac

echo "Done!"

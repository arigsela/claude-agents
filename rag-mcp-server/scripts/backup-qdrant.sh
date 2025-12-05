#!/bin/bash
# Backup Qdrant data for portability
#
# Usage:
#   Local Docker: ./scripts/backup-qdrant.sh docker
#   Kubernetes:   ./scripts/backup-qdrant.sh k8s
#
# Output: ./backups/qdrant-backup-YYYYMMDD-HHMMSS.tar.gz

set -e

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/qdrant-backup-${TIMESTAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

MODE="${1:-docker}"

case "${MODE}" in
  docker)
    echo "Backing up Qdrant from Docker volume..."

    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "rag-mcp-qdrant"; then
      echo "Warning: qdrant container not running, backing up volume directly"
    fi

    # Create backup from Docker volume
    docker run --rm \
      -v rag-mcp-server_qdrant_storage:/data:ro \
      -v "$(pwd)/${BACKUP_DIR}":/backup \
      alpine:latest \
      tar czf "/backup/qdrant-backup-${TIMESTAMP}.tar.gz" -C /data .

    echo "Backup created: ${BACKUP_FILE}"
    ;;

  k8s|kubernetes)
    echo "Backing up Qdrant from Kubernetes..."

    NAMESPACE="${QDRANT_NAMESPACE:-rag-mcp}"
    POD=$(kubectl get pods -n "${NAMESPACE}" -l app=qdrant -o jsonpath='{.items[0].metadata.name}')

    if [ -z "${POD}" ]; then
      echo "Error: No Qdrant pod found in namespace ${NAMESPACE}"
      exit 1
    fi

    echo "Found pod: ${POD}"

    # Create snapshot via Qdrant API
    echo "Creating Qdrant snapshot..."
    kubectl exec -n "${NAMESPACE}" "${POD}" -- \
      wget -q -O - --post-data='{}' \
      'http://localhost:6333/snapshots' | tee /tmp/snapshot-response.json

    # Extract snapshot name from response
    SNAPSHOT_NAME=$(cat /tmp/snapshot-response.json | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)

    if [ -z "${SNAPSHOT_NAME}" ]; then
      echo "Error: Failed to create snapshot"
      exit 1
    fi

    echo "Snapshot created: ${SNAPSHOT_NAME}"

    # Copy snapshot to local
    kubectl cp "${NAMESPACE}/${POD}:/qdrant/storage/snapshots/${SNAPSHOT_NAME}" \
      "${BACKUP_DIR}/${SNAPSHOT_NAME}"

    echo "Backup created: ${BACKUP_DIR}/${SNAPSHOT_NAME}"
    ;;

  *)
    echo "Usage: $0 [docker|k8s]"
    exit 1
    ;;
esac

# Show backup size
ls -lh "${BACKUP_FILE}" 2>/dev/null || ls -lh "${BACKUP_DIR}"/*"${TIMESTAMP}"* 2>/dev/null || true

echo "Done!"

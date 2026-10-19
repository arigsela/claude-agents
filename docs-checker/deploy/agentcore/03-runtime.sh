#!/usr/bin/env bash
# One AgentCore runtime per repo: docs_checker_bedrock or docs_checker_opensearch.
#
#   bash docs-checker/deploy/agentcore/03-runtime.sh <bedrock|opensearch> \
#     --image <ecr uri>@sha256:<hex> [--check|--apply]
#
# --check (default) makes describe/get calls only. --apply creates the security group
# docs-checker-runtime if missing (no ingress, egress TCP 443 only), then creates or
# updates the runtime with ONE full request built by the same function both times:
# update-agent-runtime replaces the whole configuration, and a request that leaves out
# filesystemConfigurations silently drops session storage. After READY it reads the
# runtime back and fails unless session storage, VPC mode and the image digest are what
# it sent. A tag-only image reference is refused: the runtime pins a digest.
set -euo pipefail

# shellcheck source=env.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

usage() { echo "usage: $0 <bedrock|opensearch> --image <uri>@sha256:<hex> [--check|--apply]" >&2; exit 2; }
name="${1:-}"; shift || true
case "$name" in bedrock | opensearch) ;; *) usage ;; esac
image="" mode=--check
while [ $# -gt 0 ]; do
  case "$1" in
    --image) image="${2:-}"; shift 2 ;;
    --check | --apply) mode="$1"; shift ;;
    *) usage ;;
  esac
done
if ! [[ "$image" =~ ^[0-9]{12}\.dkr\.ecr\.$REGION\.amazonaws\.com/$ECR_REPO@sha256:[0-9a-f]{64}$ ]]; then
  echo "refusing image '$image': it must be $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$ECR_REPO@sha256:<64 hex>" >&2
  exit 2
fi

runtime_name="docs_checker_$name"
env_file="$here_agentcore/runtimes/$name.env"
ac=(aws bedrock-agentcore-control "${P[@]}")
missing=0
report() {
  echo "$1 $2"
  if [ "$1" = MISSING ]; then missing=$((missing + 1)); fi
}

for file in "$OUT_DIR/foundation.env" "$OUT_DIR/gateway.env" "$env_file"; do
  [ -r "$file" ] || { echo "missing $file (run 01-foundation.sh and 02-gateway.sh first)" >&2; exit 1; }
done
# shellcheck disable=SC1091
source "$OUT_DIR/foundation.env"
# shellcheck disable=SC1091
source "$OUT_DIR/gateway.env"

security_group_id() {
  aws ec2 describe-security-groups "${P[@]}" \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=$SECURITY_GROUP_NAME" \
    --query 'SecurityGroups[0].GroupId' --output text | sed 's/^None$//'
}

ensure_security_group() {
  local id
  id="$(security_group_id)"
  if [ -n "$id" ]; then report OK "sg $SECURITY_GROUP_NAME $id"; return; fi
  if [ "$mode" = --check ]; then report MISSING "sg $SECURITY_GROUP_NAME"; return; fi
  id="$(aws ec2 create-security-group "${P[@]}" --vpc-id "$VPC_ID" --group-name "$SECURITY_GROUP_NAME" \
    --description "docs-checker AgentCore runtime: no ingress, egress 443" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$SECURITY_GROUP_NAME},{Key=Consumer,Value=docs-checker},{Key=Environment,Value=sb-asela}]" \
    --query GroupId --output text)"
  # A new group allows all egress; replace that with TCP 443 only.
  aws ec2 revoke-security-group-egress "${P[@]}" --group-id "$id" \
    --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' >/dev/null
  aws ec2 authorize-security-group-egress "${P[@]}" --group-id "$id" \
    --ip-permissions '[{"IpProtocol":"tcp","FromPort":443,"ToPort":443,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"Bedrock, Gateway, ECR, CloudWatch, GitHub via NAT"}]}]' >/dev/null
  report OK "sg $SECURITY_GROUP_NAME $id (created, egress 443 only)"
}

environment_json() {
  local ids
  ids="$(jq -cn --arg h "$HAIKU_PROFILE_ARN" --arg s "$SONNET_PROFILE_ARN" \
    '{"claude-haiku-5-5": $h, "claude-sonnet-5-5": $s}')"
  grep -vE '^\s*(#|$)' "$env_file" | jq -Rn --arg ids "$ids" --arg mcp "$MCP_URL" --arg region "$REGION" '
    [inputs | capture("^(?<key>[A-Z0-9_]+)=(?<value>.*)$")] | from_entries
    + {DOCS_CHECKER_BEDROCK_MODEL_IDS: $ids, DOCS_CHECKER_MCP_URL: $mcp, AWS_REGION: $region}'
}

# The one request body create and update share (everything but the name or id).
runtime_config() {
  local sg="$1"
  jq -n \
    --arg image "$image" --arg role "$ROLE_ARN" --arg sg "$sg" --arg mount "$SESSION_MOUNT" \
    --argjson subnets "$(printf '%s\n' "${SUBNETS[@]}" | jq -R . | jq -s .)" \
    --argjson idle "$IDLE_TIMEOUT_S" --argjson life "$MAX_LIFETIME_S" \
    --argjson env "$(environment_json)" --arg description "docs-checker for chg-infra-opentofu-$name" '{
      description: $description,
      agentRuntimeArtifact: {containerConfiguration: {containerUri: $image}},
      roleArn: $role,
      networkConfiguration: {networkMode: "VPC",
        networkModeConfig: {subnets: $subnets, securityGroups: [$sg]}},
      protocolConfiguration: {serverProtocol: "A2A"},
      lifecycleConfiguration: {idleRuntimeSessionTimeout: $idle, maxLifetime: $life},
      filesystemConfigurations: [{sessionStorage: {mountPath: $mount}}],
      environmentVariables: $env
    }'
}

runtime_id() {
  "${ac[@]}" list-agent-runtimes \
    --query "agentRuntimes[?agentRuntimeName=='$runtime_name'].agentRuntimeId | [0]" --output text \
    | sed 's/^None$//'
}

wait_ready() {
  local id="$1" status
  for _ in $(seq 1 120); do
    status="$("${ac[@]}" get-agent-runtime --agent-runtime-id "$id" --query status --output text)"
    case "$status" in
      READY) return 0 ;;
      *FAILED*) echo "runtime $status: $("${ac[@]}" get-agent-runtime --agent-runtime-id "$id" --query failureReason --output text)" >&2; return 1 ;;
    esac
    sleep 5
  done
  echo "timed out waiting for READY (last: $status)" >&2; return 1
}

verify_read_back() {
  local id="$1" got
  got="$("${ac[@]}" get-agent-runtime --agent-runtime-id "$id" --output json)"
  jq -e --arg image "$image" --arg mount "$SESSION_MOUNT" '
    .agentRuntimeArtifact.containerConfiguration.containerUri == $image
    and .networkConfiguration.networkMode == "VPC"
    and ([.filesystemConfigurations[]?.sessionStorage.mountPath] == [$mount])
    and .protocolConfiguration.serverProtocol == "A2A"' <<<"$got" >/dev/null \
    || { echo "read-back mismatch:" >&2; jq '{artifact: .agentRuntimeArtifact, net: .networkConfiguration, fs: .filesystemConfigurations, proto: .protocolConfiguration}' <<<"$got" >&2; return 1; }
  report OK "runtime $runtime_name read back: image digest, VPC, session storage $SESSION_MOUNT, A2A"
}

ensure_security_group
sg="$(security_group_id)"
id="$(runtime_id)"
if [ "$mode" = --check ]; then
  if [ -n "$id" ]; then
    report OK "runtime $runtime_name $id ($("${ac[@]}" get-agent-runtime --agent-runtime-id "$id" --query status --output text))"
  else
    report MISSING "runtime $runtime_name"
  fi
  if [ -n "$sg" ]; then runtime_config "$sg" | jq '.environmentVariables |= keys' ; fi
else
  config="$(runtime_config "$sg")"
  if [ -z "$id" ]; then
    jq --arg n "$runtime_name" '. + {agentRuntimeName: $n, tags: {Consumer: "docs-checker", Environment: "sb-asela"}}' <<<"$config" \
      | with_json_input "${ac[@]}" create-agent-runtime >/dev/null
    id="$(runtime_id)"
    report OK "runtime $runtime_name $id (created)"
  else
    jq --arg id "$id" '. + {agentRuntimeId: $id}' <<<"$config" \
      | with_json_input "${ac[@]}" update-agent-runtime >/dev/null
    report OK "runtime $runtime_name $id (updated with the full configuration)"
  fi
  wait_ready "$id"
  verify_read_back "$id"
  arn="$("${ac[@]}" get-agent-runtime --agent-runtime-id "$id" --query agentRuntimeArn --output text)"
  printf 'RUNTIME_ID=%s\nRUNTIME_ARN=%s\nIMAGE=%s\n' "$id" "$arn" "$image" | tee "$OUT_DIR/runtime-$name.env"
fi

if [ "$missing" -gt 0 ]; then echo "$missing missing"; fi
exit 0

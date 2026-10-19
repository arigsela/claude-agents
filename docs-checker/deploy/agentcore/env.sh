# shellcheck shell=bash disable=SC2034 # constants consumed by the scripts that source this
# Shared constants for the AgentCore deploy scripts. Sourced, never run.
# sb-asela only: every AWS call takes "${P[@]}" so the profile is never ambient.
ACCOUNT=414696729697
REGION=us-west-2
PROFILE=sb-asela
P=(--profile "$PROFILE" --region "$REGION")

VPC_ID=vpc-0e8e76490d5ea04ae
# Private subnets, one per AZ (usw2-az2, usw2-az1, usw2-az3), each behind its own NAT gateway.
SUBNETS=(subnet-01710edde6972a0b0 subnet-0271ab029fabc7f10 subnet-0d4e90025ee4dcb38)

ROLE_NAME=docs-checker-agentcore
ECR_REPO=docs-checker
FINDINGS_LOG_GROUP=/docs-checker/findings
FINDINGS_RETENTION_DAYS=30

HAIKU_PROFILE_NAME=docs-checker-claude-haiku-5-5
SONNET_PROFILE_NAME=docs-checker-claude-sonnet-5-5
HAIKU_MODEL_ID=anthropic.claude-haiku-5-5
SONNET_MODEL_ID=anthropic.claude-sonnet-5-5

TAGS_KV=(Consumer=docs-checker Environment=sb-asela Service=Bedrock)

here_agentcore="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$here_agentcore/out"

GATEWAY_NAME=docs-checker
GATEWAY_ROLE_NAME=docs-checker-gateway
GATEWAY_TARGET_NAME=github
GITHUB_CREDENTIAL_PROVIDER=docs-checker-github
# GitHub's hosted MCP server, repos toolset only, read-only mode.
GITHUB_MCP_URL=https://api.githubcopilot.com/mcp/x/repos/readonly

SECURITY_GROUP_NAME=docs-checker-runtime
SESSION_MOUNT=/mnt/workspace
# Overridable for a test run (IDLE_TIMEOUT_S=300 bash 03-runtime.sh ...); the default
# keeps an approval pause alive for an hour.
IDLE_TIMEOUT_S="${IDLE_TIMEOUT_S:-3600}"
MAX_LIFETIME_S=28800

# with_json_input CMD...: run CMD with --cli-input-json read from a private temp file
# holding stdin. aws-cli 2.34 cannot read --cli-input-json from a pipe (file:///dev/stdin
# is "Invalid JSON"), so the JSON goes to a 0600 file in a 0700 directory, removed as
# soon as CMD returns.
with_json_input() {
  local dir status=0
  dir="$(umask 077 && mktemp -d)"
  cat >"$dir/input.json"
  "$@" --cli-input-json "file://$dir/input.json" || status=$?
  rm -rf "$dir"
  return "$status"
}

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

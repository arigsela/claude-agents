#!/usr/bin/env bash
# AgentCore Gateway for docs-checker in sb-asela: the GitHub PAT credential provider,
# the gateway role, the gateway (MCP, AWS_IAM inbound) and its `github` target, GitHub's
# hosted MCP server in read-only mode with the repos toolset.
#
#   bash docs-checker/deploy/agentcore/02-gateway.sh            # --check: read-only
#   bash docs-checker/deploy/agentcore/02-gateway.sh --apply    # create what is missing
#
# The PAT is read from the terminal (silent) only when the credential provider is
# missing, and reaches the CLI on stdin as JSON: never argv, env or a file. --apply also
# grants the runtime role InvokeGateway on this gateway, and both modes write
# out/gateway.env (MCP_URL, GATEWAY_ARN) once the gateway exists.
set -euo pipefail

# shellcheck source=env.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

mode="${1:---check}"
case "$mode" in
  --check | --apply) ;;
  *) echo "usage: $0 [--check|--apply]" >&2; exit 2 ;;
esac

ac=(aws bedrock-agentcore-control "${P[@]}")
missing=0
report() {
  echo "$1 $2"
  if [ "$1" = MISSING ]; then missing=$((missing + 1)); fi
}

provider_arn() {
  "${ac[@]}" get-api-key-credential-provider --name "$GITHUB_CREDENTIAL_PROVIDER" \
    --query credentialProviderArn --output text 2>/dev/null || true
}

ensure_provider() {
  local arn pat
  arn="$(provider_arn)"
  if [ -n "$arn" ]; then report OK "credential-provider $GITHUB_CREDENTIAL_PROVIDER $arn"; return; fi
  if [ "$mode" = --check ]; then report MISSING "credential-provider $GITHUB_CREDENTIAL_PROVIDER"; return; fi
  if ! { : </dev/tty; } 2>/dev/null; then
    report MISSING "credential-provider $GITHUB_CREDENTIAL_PROVIDER (the PAT is read from a terminal: run --apply in an interactive shell)"
    return
  fi
  printf 'Fine-grained GitHub PAT (input hidden): ' >/dev/tty
  IFS= read -rs pat </dev/tty
  printf '\n' >/dev/tty
  if [ -z "$pat" ]; then echo "empty PAT; nothing created" >&2; exit 1; fi
  jq -n --arg name "$GITHUB_CREDENTIAL_PROVIDER" --arg key "$pat" '{name: $name, apiKey: $key}' \
    | "${ac[@]}" create-api-key-credential-provider --cli-input-json file:///dev/stdin >/dev/null
  unset pat
  report OK "credential-provider $GITHUB_CREDENTIAL_PROVIDER $(provider_arn) (created)"
}

ensure_gateway_role() {
  if aws iam get-role --profile "$PROFILE" --role-name "$GATEWAY_ROLE_NAME" >/dev/null 2>&1; then
    report OK "iam-role $GATEWAY_ROLE_NAME"
  elif [ "$mode" = --check ]; then
    report MISSING "iam-role $GATEWAY_ROLE_NAME"; return
  else
    aws iam create-role --profile "$PROFILE" --role-name "$GATEWAY_ROLE_NAME" \
      --description "docs-checker AgentCore Gateway role (reads the GitHub PAT)" \
      --assume-role-policy-document "file://$here_agentcore/policies/execution-role-trust.json" \
      --tags Key=Consumer,Value=docs-checker Key=Environment,Value=sb-asela >/dev/null
    report OK "iam-role $GATEWAY_ROLE_NAME (created)"
  fi
  if [ "$mode" = --apply ]; then
    aws iam put-role-policy --profile "$PROFILE" --role-name "$GATEWAY_ROLE_NAME" \
      --policy-name docs-checker-gateway \
      --policy-document "file://$here_agentcore/policies/gateway-role.json"
    report OK "iam-role-policy $GATEWAY_ROLE_NAME/docs-checker-gateway (put)"
  fi
}

gateway_id() {
  "${ac[@]}" list-gateways --query "items[?name=='$GATEWAY_NAME'].gatewayId | [0]" \
    --output text | sed 's/^None$//'
}

wait_ready() { # wait_ready <describe command...>: poll status until READY, fail on *FAILED
  local status
  for _ in $(seq 1 60); do
    status="$("$@" --query status --output text)"
    case "$status" in
      READY) return 0 ;;
      *FAILED*) echo "status $status: $("$@" --query statusReasons --output text)" >&2; return 1 ;;
    esac
    sleep 5
  done
  echo "timed out waiting for READY (last: $status)" >&2
  return 1
}

ensure_gateway() {
  local id
  id="$(gateway_id)"
  if [ -n "$id" ]; then report OK "gateway $GATEWAY_NAME $id"; return; fi
  if [ "$mode" = --check ]; then report MISSING "gateway $GATEWAY_NAME"; return; fi
  "${ac[@]}" create-gateway --name "$GATEWAY_NAME" \
    --description "docs-checker read-only GitHub tools" \
    --role-arn "arn:aws:iam::$ACCOUNT:role/$GATEWAY_ROLE_NAME" \
    --protocol-type MCP --authorizer-type AWS_IAM \
    --tags Consumer=docs-checker,Environment=sb-asela >/dev/null
  id="$(gateway_id)"
  wait_ready "${ac[@]}" get-gateway --gateway-identifier "$id"
  report OK "gateway $GATEWAY_NAME $id (created)"
}

ensure_target() {
  local id="$1" provider="$2" target config credentials
  if [ -z "$id" ]; then report MISSING "gateway-target $GATEWAY_TARGET_NAME (no gateway)"; return; fi
  target="$("${ac[@]}" list-gateway-targets --gateway-identifier "$id" \
    --query "items[?name=='$GATEWAY_TARGET_NAME'].[targetId,status] | [0]" --output text | sed 's/^None$//')"
  if [ -n "$target" ]; then report OK "gateway-target $GATEWAY_TARGET_NAME $target"; return; fi
  if [ "$mode" = --check ]; then report MISSING "gateway-target $GATEWAY_TARGET_NAME"; return; fi
  if [ -z "$provider" ]; then report MISSING "gateway-target $GATEWAY_TARGET_NAME (no credential provider yet)"; return; fi
  config="$(jq -n --arg url "$GITHUB_MCP_URL" '{mcp: {mcpServer: {endpoint: $url}}}')"
  credentials="$(jq -n --arg arn "$provider" '[{credentialProviderType: "API_KEY",
    credentialProvider: {apiKeyCredentialProvider: {providerArn: $arn,
      credentialParameterName: "Authorization", credentialPrefix: "Bearer",
      credentialLocation: "HEADER"}}}]')"
  "${ac[@]}" create-gateway-target --gateway-identifier "$id" --name "$GATEWAY_TARGET_NAME" \
    --description "GitHub hosted MCP, repos toolset, read-only" \
    --target-configuration "$config" --credential-provider-configurations "$credentials" >/dev/null
  target="$("${ac[@]}" list-gateway-targets --gateway-identifier "$id" \
    --query "items[?name=='$GATEWAY_TARGET_NAME'].targetId | [0]" --output text)"
  wait_ready "${ac[@]}" get-gateway-target --gateway-identifier "$id" --target-id "$target"
  report OK "gateway-target $GATEWAY_TARGET_NAME $target READY (created)"
}

ensure_invoke_grant() {
  local arn="$1"
  if aws iam get-role-policy --profile "$PROFILE" --role-name "$ROLE_NAME" \
    --policy-name docs-checker-gateway-invoke >/dev/null 2>&1; then
    report OK "iam-role-policy $ROLE_NAME/docs-checker-gateway-invoke"
  elif [ "$mode" = --check ]; then
    report MISSING "iam-role-policy $ROLE_NAME/docs-checker-gateway-invoke"
  fi
  if [ "$mode" = --apply ] && [ -n "$arn" ]; then
    aws iam put-role-policy --profile "$PROFILE" --role-name "$ROLE_NAME" \
      --policy-name docs-checker-gateway-invoke \
      --policy-document "$(jq -n --arg arn "$arn" '{Version: "2012-10-17", Statement: [
        {Sid: "InvokeDocsCheckerGateway", Effect: "Allow",
         Action: "bedrock-agentcore:InvokeGateway", Resource: $arn}]}')"
    report OK "iam-role-policy $ROLE_NAME/docs-checker-gateway-invoke (put)"
  fi
}

ensure_gateway_role
ensure_gateway
ensure_provider
id="$(gateway_id)"
ensure_target "$id" "$(provider_arn)"
if [ -n "$id" ]; then
  read -r gateway_arn mcp_url < <("${ac[@]}" get-gateway --gateway-identifier "$id" \
    --query '[gatewayArn,gatewayUrl]' --output text)
  ensure_invoke_grant "$gateway_arn"
  mkdir -p "$OUT_DIR"
  printf 'GATEWAY_ARN=%s\nMCP_URL=%s\n' "$gateway_arn" "$mcp_url" | tee "$OUT_DIR/gateway.env"
else
  ensure_invoke_grant ""
fi

if [ "$missing" -gt 0 ]; then echo "$missing missing"; fi
exit 0

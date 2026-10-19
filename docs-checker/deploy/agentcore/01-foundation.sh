#!/usr/bin/env bash
# AgentCore foundation for docs-checker in sb-asela: two application inference profiles,
# the ECR repository, the findings log group and the runtime execution role.
#
#   bash docs-checker/deploy/agentcore/01-foundation.sh            # --check: read-only
#   bash docs-checker/deploy/agentcore/01-foundation.sh --apply    # create what is missing
#
# --check prints one "OK <resource>" or "MISSING <resource>" line per resource and makes
# describe/list/get calls only. --apply describes before every create, so it can be re-run.
# The role's inline policy is re-put on every --apply because it is rendered from the profile
# ARNs, which exist only after the profiles do. Both modes write out/foundation.env when both
# profiles exist; the runtime deploy script reads the ARNs from there.
#
# The runtime role carries no GetResourceApiKey: Gateway, not the runtime, fetches the GitHub
# PAT from AgentCore Identity, so that permission belongs to the gateway role (Task 6), along
# with the runtime's InvokeGateway grant.
set -euo pipefail

# shellcheck source=env.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

mode="${1:---check}"
case "$mode" in
  --check | --apply) ;;
  *) echo "usage: $0 [--check|--apply]" >&2; exit 2 ;;
esac

missing=0
report() { # report OK|MISSING <resource>
  echo "$1 $2"
  if [ "$1" = MISSING ]; then missing=$((missing + 1)); fi
}

bedrock_tags() { # bedrock wants key=,value= pairs
  local model_id="$1" kv
  for kv in "${TAGS_KV[@]}" "Model=$model_id"; do printf 'key=%s,value=%s ' "${kv%%=*}" "${kv#*=}"; done
}
upper_tags() { # ECR and IAM want Key=,Value= pairs
  local kv
  for kv in "${TAGS_KV[@]}"; do printf 'Key=%s,Value=%s ' "${kv%%=*}" "${kv#*=}"; done
}
logs_tags() { # CloudWatch Logs wants k=v,k=v
  local IFS=,
  echo "${TAGS_KV[*]}"
}

profile_arn() { # profile_arn <name>: the application profile's ARN, empty when absent
  aws bedrock list-inference-profiles "${P[@]}" --type-equals APPLICATION \
    --query "inferenceProfileSummaries[?inferenceProfileName=='$1'].inferenceProfileArn | [0]" \
    --output text | sed 's/^None$//'
}

ensure_profile() { # ensure_profile <name> <model id>
  local name="$1" model_id="$2" arn source_arn
  arn="$(profile_arn "$name")"
  if [ -n "$arn" ]; then report OK "inference-profile $name $arn"; return; fi
  if [ "$mode" = --check ]; then report MISSING "inference-profile $name"; return; fi
  source_arn="arn:aws:bedrock:$REGION:$ACCOUNT:inference-profile/global.$model_id"
  # shellcheck disable=SC2046 # one shorthand argument per tag
  aws bedrock create-inference-profile "${P[@]}" --inference-profile-name "$name" \
    --description "docs-checker on AgentCore via global.$model_id" \
    --model-source "copyFrom=$source_arn" --tags $(bedrock_tags "$model_id") >/dev/null
  report OK "inference-profile $name $(profile_arn "$name") (created)"
}

ensure_ecr() {
  if aws ecr describe-repositories "${P[@]}" --repository-names "$ECR_REPO" >/dev/null 2>&1; then
    report OK "ecr $ECR_REPO"; return
  fi
  if [ "$mode" = --check ]; then report MISSING "ecr $ECR_REPO"; return; fi
  # shellcheck disable=SC2046
  aws ecr create-repository "${P[@]}" --repository-name "$ECR_REPO" \
    --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true \
    --tags $(upper_tags) >/dev/null
  report OK "ecr $ECR_REPO (created)"
}

ensure_log_group() {
  local found
  found="$(aws logs describe-log-groups "${P[@]}" --log-group-name-prefix "$FINDINGS_LOG_GROUP" \
    --query "logGroups[?logGroupName=='$FINDINGS_LOG_GROUP'].retentionInDays | [0]" --output text)"
  if [ "$found" = "$FINDINGS_RETENTION_DAYS" ]; then
    report OK "log-group $FINDINGS_LOG_GROUP retention=$found"; return
  fi
  if [ "$mode" = --check ]; then report MISSING "log-group $FINDINGS_LOG_GROUP retention=$FINDINGS_RETENTION_DAYS (now: $found)"; return; fi
  if [ "$found" = None ]; then
    if ! aws logs describe-log-groups "${P[@]}" --log-group-name-prefix "$FINDINGS_LOG_GROUP" \
      --query "logGroups[?logGroupName=='$FINDINGS_LOG_GROUP'].logGroupName" --output text | grep -q .; then
      aws logs create-log-group "${P[@]}" --log-group-name "$FINDINGS_LOG_GROUP" --tags "$(logs_tags)"
    fi
  fi
  aws logs put-retention-policy "${P[@]}" --log-group-name "$FINDINGS_LOG_GROUP" \
    --retention-in-days "$FINDINGS_RETENTION_DAYS"
  report OK "log-group $FINDINGS_LOG_GROUP retention=$FINDINGS_RETENTION_DAYS (applied)"
}

ensure_role() {
  local haiku_arn="$1" sonnet_arn="$2" rendered
  if aws iam get-role --profile "$PROFILE" --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    report OK "iam-role $ROLE_NAME"
  elif [ "$mode" = --check ]; then
    report MISSING "iam-role $ROLE_NAME"
  else
    # shellcheck disable=SC2046
    aws iam create-role --profile "$PROFILE" --role-name "$ROLE_NAME" \
      --description "docs-checker AgentCore Runtime execution role" \
      --assume-role-policy-document "file://$here_agentcore/policies/execution-role-trust.json" \
      --tags $(upper_tags) >/dev/null
    report OK "iam-role $ROLE_NAME (created)"
  fi

  if aws iam get-role-policy --profile "$PROFILE" --role-name "$ROLE_NAME" --policy-name docs-checker-runtime >/dev/null 2>&1; then
    report OK "iam-role-policy $ROLE_NAME/docs-checker-runtime"
  elif [ "$mode" = --check ]; then
    report MISSING "iam-role-policy $ROLE_NAME/docs-checker-runtime"
  fi
  if [ "$mode" = --apply ]; then
    if [ -z "$haiku_arn" ] || [ -z "$sonnet_arn" ]; then
      echo "refusing to put the role policy: a profile ARN is empty" >&2; exit 1
    fi
    rendered="$(sed -e "s|@HAIKU_PROFILE_ARN@|$haiku_arn|" -e "s|@SONNET_PROFILE_ARN@|$sonnet_arn|" \
      "$here_agentcore/policies/execution-role.json")"
    aws iam put-role-policy --profile "$PROFILE" --role-name "$ROLE_NAME" \
      --policy-name docs-checker-runtime --policy-document "$rendered"
    report OK "iam-role-policy $ROLE_NAME/docs-checker-runtime (put)"
  fi
}

ensure_profile "$HAIKU_PROFILE_NAME" "$HAIKU_MODEL_ID"
ensure_profile "$SONNET_PROFILE_NAME" "$SONNET_MODEL_ID"
ensure_ecr
ensure_log_group
haiku_arn="$(profile_arn "$HAIKU_PROFILE_NAME")"
sonnet_arn="$(profile_arn "$SONNET_PROFILE_NAME")"
ensure_role "$haiku_arn" "$sonnet_arn"

if [ -n "$haiku_arn" ] && [ -n "$sonnet_arn" ]; then
  mkdir -p "$OUT_DIR"
  role_arn="arn:aws:iam::$ACCOUNT:role/$ROLE_NAME"
  printf 'HAIKU_PROFILE_ARN=%s\nSONNET_PROFILE_ARN=%s\nROLE_ARN=%s\n' "$haiku_arn" "$sonnet_arn" "$role_arn" \
    | tee "$OUT_DIR/foundation.env"
fi

if [ "$mode" = --check ] && [ "$missing" -gt 0 ]; then echo "$missing missing"; fi
exit 0

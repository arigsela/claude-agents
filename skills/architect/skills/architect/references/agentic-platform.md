# Agentic Platform

> The agentic platform lens of the `architect` skill: designing the platform that lets AI
> agents do delivery and operations work safely. Examples are coding agents opening PRs,
> agents answering from internal docs, and agents triaging alerts or taking gated
> actions. To score a client and produce deliverables, use the `infra-maturity-assessment`
> skill's AI & Agent Platform tab.

## Before designing: three checks

1. **Size.** Roughly 50 or more developers, or a concrete multi-team agent use case.
   Below that, recommend tool-level guardrails instead of a platform: instruction files
   in repos, normal PR review for agent changes, and provider spend limits.
2. **Foundation.** A working internal developer platform: CI/CD, IaC and self-service.
   Agents ride on it. Weave's article puts it this way: "If you don't yet have a good
   IDP, forget building an AEP."
3. **Ownership.** All three are in place:
   - a named owner for the agent platform;
   - a sponsor with budget;
   - a legal and data-protection path for sending code and data to model providers.

## Reference architecture: three layers

This is the Agentic Development Platform model from PlatformCon 2026. Weave now also
calls it an "Agentic Engineering Platform".

- **Tooling.** The IDP and its planes:
  - developer control plane;
  - integration and delivery;
  - resources;
  - observability;
  - security.

  The tools must work for agents too: APIs, rate limits that survive parallel calls,
  structured output and clear failure modes.
- **Path specifications.** How an agent carries out a workflow. There are three kinds:
  - **Probabilistic:** an agent does the work, and evals or a human judge it. Example:
    agent PR review.
  - **Deterministic:** pipelines that behave the same whether a human or an agent
    committed. Examples: CI, scans, deploys.
  - **Hybrid:** the agent proposes, a deterministic gate checks, the agent reads the
    failure and retries, within a retry budget and a definition of done.
- **Agent infrastructure.**
  - **Harness:** context, capability (tools), execution (where and how agents run) and
    evaluation.
  - **Governance:** identity, agent security and agent observability, built once for
    every agent, not per agent.
  - **Models:** providers, inference endpoints and hosting. This is a platform-owned
    plane, not a purchasing decision.

## Autonomy levels and what each needs

| Level | Human role | Needs, in addition to the level before |
|---|---|---|
| A1 · Human in the loop | Approves suggestions line by line | Visible spend; instruction files |
| A2 · Human on the loop | Agents open PRs in parallel; humans review outcomes | Per-agent identity, sandboxes, evals and agent security |
| A3 · Human as orchestrator | Background agents and signal-triggered work | Capability classes with approvals, a durable audit record, a model gateway with budgets, specified paths, and state management for long-running agents |
| A4 · Human outside the loop | Agents act alone within guardrails | Narrow declared classes only, with policy enforcement fail-closed and eval evidence per class. Treat it as a projection. |

Recommend the level the controls support today, not the level the client wants. Running
level 3 on level 1 controls is the most common failure ("autonomy without governance").

## Design questions, by pillar

Use these questions in discovery and design reviews.

- **Identity.**
  - How does each agent authenticate?
  - Can every action be traced to the agent and to the human or system that asked?
  - Are callers to agents verified, not only agents to tools?
- **Context.**
  - Where does an agent get the truth about a service?
  - Who owns that context, how is it kept current, and does CI check it?
- **Capability.**
  - Which tools change state?
  - Which agent classes exist (read, propose, act)?
  - Is that enforced in the prompt, at a gateway, or at admission? Only the last two
    count.
- **Execution.**
  - Where do agents run, and what can they reach?
  - What stops a runaway loop?
- **Evaluation.**
  - What tells you that a prompt, model or tool change made an agent worse?
  - Does that result block promotion?
- **Security.**
  - What happens when untrusted text, such as an issue body, a log line or a web page,
    says "ignore previous instructions"?
  - What could the agent exfiltrate, and to where?
- **Observability.**
  - Can you reconstruct one agent-made change end to end: request, tool calls, approval
    and result?
  - What did it cost?
- **Models.**
  - Who decides which models are allowed in each environment?
  - Where are budgets and rate limits enforced?

## Build order that worked

1. **Docs as context:**
   - instruction files in each repo;
   - a per-service docs contract (what every service documents);
   - CI checks that the docs exist and are current.
2. **Identity.**
   - Make agents and their callers principals.
   - Give each agent its own source-control app identity, so its PRs are attributable.
3. **Capability classes and approval.**
   - Defaults: read-only for investigation, propose for opening PRs, act for gated
     mutations.
   - Require human approval on every mutating tool.
   - Enforce this fail-closed at admission or the gateway.
4. **An audit record:** who asked, which agent ran, what it called, and what was
   approved.
5. **Evaluation as a release gate:** a change to an agent definition runs its eval set
   and blocks or alerts on regression.
6. **Climb the ladder one class at a time:**
   - read-only dispatch and investigation;
   - agent-authored PRs that humans merge;
   - gated actions (an alert leads to a proposed action, a human approves, the agent
     acts);
   - policy-based merging for narrow, proven classes such as dependency bumps and
     docs-only changes.

Pilot one path end to end, with kill criteria, before adding the next. Measure time
saved, cost per task and the DORA metrics before and after.

## Control catalog with familiar equivalents

| Control | AWS | Azure / Microsoft | Open source / neutral |
|---|---|---|---|
| Agent runtime | Bedrock AgentCore Runtime | Azure AI Foundry Agent Service | kagent (CNCF), LangGraph, Claude Code / Codex in CI |
| Agent identity | IAM roles, EKS Pod Identity, AgentCore Identity | Entra workload identities, managed identities | Kubernetes service accounts, SPIFFE/SPIRE, one GitHub App per agent |
| Caller verification | API Gateway / ALB JWT validation | API Management, Entra tokens | Istio RequestAuthentication, agentgateway, OIDC via Okta/Dex |
| Capability policy | IAM + SCPs, AgentCore Gateway | Azure Policy, API Management | ValidatingAdmissionPolicy, Kyverno, OPA Gatekeeper, an MCP gateway |
| Human approval | Step Functions callbacks, CodePipeline manual approvals | GitHub Environments, Teams approvals | Slack approval buttons, A2A input-required pauses |
| Sandboxes | AgentCore Runtime, ECS/Fargate tasks | Container Apps sessions | Namespaces + NetworkPolicy, gVisor/Kata, ephemeral CI runners |
| Context | Bedrock Knowledge Bases | Copilot instructions and Spaces | AGENTS.md, Backstage TechDocs, MCP documentation servers |
| Evals | AgentCore Evaluations | Azure AI Foundry evaluations | promptfoo, DeepEval, Inspect, a CI job over an eval corpus |
| Model gateway and budgets | Bedrock model access policies + a gateway account | API Management AI gateway | LiteLLM, agentgateway, Kong AI Gateway |
| Traces and audit | CloudTrail, CloudWatch, an S3 audit store | Azure Monitor, Log Analytics | OpenTelemetry GenAI traces, Langfuse, Grafana/Datadog |

## Anti-patterns

- Over-automating a small organization.
- Treating an agent's first-run failure as a defect, instead of designing loops that
  converge.
- Building governance separately for each agent.
- Treating model access as a purchasing decision, which fragments governance and cost
  attribution.
- Autonomy ahead of controls: level 3 on a level 1 base.
- **Approval fatigue.** Approving everything means approving nothing, so tier approvals
  by consequence.
- Agent changes that skip the CI and review human changes go through.
- **Single-owner designs.** A one-person reference build can say "the owner merges". A
  client needs team ownership and separation of duties designed in from the start.

## Using a reference build

Patterns, contracts and the build order carry over from a reference build. Its
specifics usually don't: a single cluster, alpha runtimes, one approver, a tiny budget.
Map each control to the client's stack using the catalog above. Never name a reference
build or another client in a client deliverable.

## Sources

- Weave Intelligence, "What is an agentic development platform" (2026-09):
  https://weaveintelligence.io/blog/what-is-an-agentic-development-platform
- PlatformCon 2026, "Architecting Agentic Development Platforms", Ajay Chankramath and
  Kaspar von Grünberg: https://www.youtube.com/watch?v=NbvXWNwI2wc
- PlatformCon 2026, "Agent Infrastructure", Dilek Altin: https://www.youtube.com/watch?v=jQX8DJq6MLw
- PlatformCon 2026, "The four levels of agentic development", Mallory Haigh:
  https://www.youtube.com/watch?v=BHKPYncP8xE
- PlatformCon 2026 wrap-up, with talk links including the Booking.com and Fiserv case
  studies: https://platformengineering.org/blog/platformcon-2026-wrap-up-no-ai-at-scale-without-platform-engineering
- AWS Prescriptive Guidance, AgentOps maturity roadmap, platform operations:
  https://docs.aws.amazon.com/prescriptive-guidance/latest/agent-ops-maturity-roadmap-for-enterprise-ai/platform-operations.html
- Microsoft, "Platform Engineering for the Agentic AI era" (2026-03):
  https://devblogs.microsoft.com/all-things-azure/platform-engineering-for-the-agentic-ai-era/
- Kief Morris, "Humans and Agents in Software Engineering Loops" (2026-03):
  https://martinfowler.com/articles/exploring-gen-ai/humans-and-agents.html
- Patrick Debois, "Context is the new code" (InfoQ):
  https://www.infoq.com/presentations/context-as-code-devops-agents/
- CNCF, "The autonomous enterprise and the four pillars of platform control" (2026-01):
  https://www.cncf.io/blog/2026/01/23/the-autonomous-enterprise-and-the-four-pillars-of-platform-control-2026-forecast/

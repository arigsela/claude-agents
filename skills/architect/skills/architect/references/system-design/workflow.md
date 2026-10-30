# System Design

> System design lens of the `architect` skill. Deep material in this folder:
> `estimation.md` (capacity math and reference numbers), `building-blocks.md` (components,
> data, consistency, messaging, rate limiting, trade-offs) and `reference-designs.md`
> (worked designs and the moves they reuse).

Use this lens to design a system from requirements, or to stress-test a proposed design:
how big it has to be, which components it needs, where each kind of data lives, how
consistent each part must be, and what breaks first as it grows. The lens is
cloud-agnostic. On AWS, take the component choices to the Well-Architected lens
(`../well-architected/decisions.md`) to pick services, and to the cloud patterns lens for
service-to-service mechanics (sagas, outbox, circuit breakers).

## Workflow

| Step | Produces | Read |
|---|---|---|
| 1. Scope | 2–3 core use cases, the targets for each critical path, what is out of scope | below |
| 2. Estimate | Average and peak requests/s for reads and writes, storage growth, bandwidth, cache size, instance count | `estimation.md` |
| 3. Interfaces | The key API calls with inputs and outputs; sync or async; pagination, idempotency and rate limits | `building-blocks.md` §6 |
| 4. Data model | Entities, their access patterns, the store for each, the partition key, the consistency each needs | `building-blocks.md` §3–4 |
| 5. First design (v1) | The simplest design that meets step 1 at today's numbers | — |
| 6. Evolve | v2, v3 …: each addition names the bottleneck that forced it | `building-blocks.md`, `reference-designs.md` |
| 7. Failure and operations | Failure modes per component, SLOs, what to alert on, how it deploys and rolls back | `building-blocks.md` §8, `../platform-engineering/frameworks.md` (SRE Principles) |

When the request matches a known shape (feed, chat, file sync, notifications, checkout,
geo matching, rate limiter, leaderboard, crawler, autocomplete, payments), read its entry
in `reference-designs.md` before step 5 and adapt it; don't copy it.

### Step 1: the questions that set the design

Ask these in addition to the shared context questions in `SKILL.md`. When the client
can't answer, state an assumption, label it as one, and carry it into the estimate.

- **Load:** users or daily active users, actions per user per day, growth over 12–24 months.
- **Shape:** read-heavy or write-heavy, and by how much. A 100:1 read:write ratio leads to
  a different design than 1:1.
- **Latency:** a percentile target per critical path (p99 < 200 ms for checkout), not one
  number for the whole system.
- **Availability:** per path. Login and payments rarely need the same target as analytics.
- **Consistency:** per entity. Which data must never be stale or double-counted (money,
  stock, permissions, unique names) and which can lag (counts, feeds, recommendations).
- **Data:** size, retention, and anything that must stay in a region.
- **Geography:** single region or global; whether users must be served from near them.
- **Spikiness:** steady, daily peaks, or event bursts (sales, campaigns, kickoffs).
- **Out of scope:** say it explicitly and keep it out.

### Step 6: evolve on evidence

Start from one service and one database. Add a component only when a named problem
requires it, and name that problem:

| Pressure | Typical move |
|---|---|
| One server can't take the load, or is a single point of failure | Stateless app tier behind a load balancer, across zones |
| The same data is read over and over | Cache, cache-aside first |
| Static or media content, users far away | CDN in front of object storage |
| Reads swamp the primary database | Read replicas (accept replica lag) |
| Data size or write rate exceeds one database node | Partition by a key taken from the main access pattern |
| Slow, spiky or retryable work sits in the request path | Queue and workers |
| Text search or faceted filtering | A search index fed from the source of truth |
| One part scales or changes on a very different cadence | Split it into its own service |

Present the design as versions (v1 → v2 → v3) with the trigger for each step. A single
final diagram hides why each piece exists and invites over-engineering.

### Step 7: every component gets a failure story

For each component, answer: what happens to users when it is slow, when it is down, and
when it returns wrong or duplicate results? Then pick the SLIs that would show it and the
alert that would fire. A design is not finished while any component lacks an answer.

## Output template

```markdown
## System Design: [System Name]

### Summary
Top three findings or decisions · what to do first

### Findings by severity
Only when an existing system is being redesigned: its current problems, using the
severity scale in `SKILL.md`

### Scope and targets
Core use cases (2–3) · out of scope

| Path | Latency (p99) | Availability | Consistency |
|------|---------------|--------------|-------------|

### Assumptions and estimates
Each assumption labelled · average and peak req/s (reads, writes) · storage per year
(with replication) · bandwidth · cache size · instance count with headroom

### Design
v1 (diagram + data flow) → v2, v3 …, each with the bottleneck that triggered it

### Data model
| Entity | Access pattern | Store | Partition key | Consistency |

### Key decisions
| Decision | Options considered | Choice | What we give up |

### Failure modes and operations
| Component | Failure | User impact | Mitigation | Alert on |
SLOs and burn-rate alerts · deploy and rollback · capacity headroom

### Risks and open questions

### Roadmap
Quick wins (under a week) · short-term (1–4 weeks) · strategic (1–3 months)
```

## Anti-patterns

- **Designing before scoping:** components chosen before the read:write ratio, the latency
  target or the consistency needs are known.
- **No numbers:** "it needs to scale" with no requests/s, data size or growth rate.
- **The giant v1:** microservices, Kafka and sharding for a load one database could serve.
- **One consistency level for everything:** either everything strongly consistent (slow,
  costly) or everything eventual (oversold stock, double charges).
- **Ignoring the hot spot:** load averaged across partitions while one celebrity account,
  viral item or flash sale lands on a single key.
- **No failure story:** no answer to "what happens when the cache, the queue or a
  third-party provider is down?"
- **Unstated trade-offs:** every choice should say what it gives up.

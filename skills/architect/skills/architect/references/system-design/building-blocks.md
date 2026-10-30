# System Design Building Blocks

The components most designs are made of, with the decision rule for each choice and the
failure modes to plan for. Sections:

1. Load balancing
2. Caching
3. Data stores, replication and partitioning
4. Consistency and coordination
5. Messaging
6. APIs and client communication
7. Rate limiting and load protection
8. Failure handling and operations
9. Trade-off pairs

---

## 1. Load balancing

**Layer 4 or layer 7.** A layer-4 balancer routes TCP/UDP by address and port: fastest,
protocol-agnostic, can't see paths or headers. A layer-7 balancer terminates HTTP and
routes by host, path, header or cookie, and can retry, rewrite and terminate TLS. Use L7
for HTTP services; use L4 for non-HTTP protocols, very high connection counts, or
passing TLS through untouched.

| Algorithm | Use when | Watch out |
|---|---|---|
| Round robin | Instances are alike and requests cost about the same | Uneven when request cost varies |
| Weighted | Instances differ in size, or for canary splits | Weights need maintaining |
| Least connections / least outstanding requests | Request duration varies; long-lived connections (WebSockets, streaming) | A new or recovering instance can be flooded first |
| Latency-aware, power of two choices | Backends are heterogeneous or sometimes slow | Needs good latency signals; P2C (pick the better of two random backends) avoids herding |
| Hash (IP, header, consistent hash) | Affinity helps: per-key caches, session locality | Skewed keys make hot backends; use consistent hashing so a scale event moves few keys |

Always: active health checks plus outlier ejection; connection draining on deploys;
spread instances across zones. Sticky sessions are a smell: move session state to a
shared store so any instance can serve any request. Global traffic is split by DNS
(latency or geo routing) or anycast in front of regional balancers.

On AWS, ALB (L7) offers round robin, least outstanding requests and weighted random;
NLB is L4. See `../well-architected/decisions.md` §4.

---

## 2. Caching

**Where a cache can sit:** the client or browser, a CDN edge, a reverse proxy, inside the
app process, a shared cache (Redis, Memcached), and the database's own buffer cache. The
closer to the user, the bigger the saving and the harder the invalidation.

| Strategy | How it works | Use when | Risk |
|---|---|---|---|
| Cache-aside (lazy loading) | App reads the cache; on a miss reads the database and fills the cache | Default for read-heavy data | First read after expiry is slow; stale until TTL or delete |
| Read-through | Cache library loads from the database on a miss | Same as cache-aside, with the logic in one place | Ties the cache to the data access layer |
| Write-through | Every write goes to cache and database synchronously | Data is read soon after it's written | Slower writes; caches data nobody reads |
| Write-behind (write-back) | Write to the cache; flush to the database later | Write bursts the database can't absorb (counters, telemetry) | Data loss if the cache dies before flushing |
| Write-around | Writes go only to the database | Data written once and rarely read back | First read always misses |

**Invalidation.** Always set a TTL as a safety net. On writes, delete the key rather than
updating it, which avoids racing writers leaving an old value in place. Versioned keys
(`user:42:v7`) make invalidation a pointer change. For many caches or cross-service
data, invalidate from change events (CDC) instead of from every writer.

**Eviction.** LRU is the default. LFU suits stable popularity. TTL-only suits time-bound
data. Watch the eviction rate: steady evictions of hot keys mean the cache is too small.

| Failure mode | What happens | Fix |
|---|---|---|
| Stampede (thundering herd) | A hot key expires and thousands of requests hit the database together | Request coalescing (single-flight), a short lock per key, early probabilistic refresh, jittered TTLs |
| Hot key | One key gets most traffic and saturates one cache node | A small in-process cache in front, replicate the key, split it into N sub-keys |
| Penetration | Requests for keys that don't exist always miss | Cache negative results with a short TTL; keep a Bloom filter of the keys that exist and skip the database only when it says a key is definitely absent (a false positive just costs one read) |
| Cold cache | After a flush or deploy, the database takes full load | Warm the cache before shifting traffic; ramp traffic gradually |
| Cache as the source of truth | Data lost on eviction or restart | The database stays authoritative unless the cache is configured and run as a durable store |

Don't cache, or cache with care: anything that must be exact at the moment of use
(balances, stock at checkout, permissions just revoked), and per-user or sensitive
responses at shared layers like a CDN unless cache keys and `Cache-Control: private`/`Vary`
are right.

---

## 3. Data stores, replication and partitioning

### Choose the store by access pattern

| Store type | Pick when | Watch out | Examples |
|---|---|---|---|
| Relational | Relationships, transactions, constraints, ad-hoc queries; the default for business data | Scaling writes past one primary needs partitioning | PostgreSQL, MySQL, Aurora |
| Key-value | Lookups by key at very high rates, predictable latency | No ad-hoc queries; model every access pattern up front | DynamoDB, Redis |
| Document | Self-contained records with varying shape, read and written whole | Cross-document joins and transactions are weak or costly | MongoDB, DocumentDB |
| Wide-column | Huge write volume, time-ordered data per key (messages, events) | Query by partition key only; tombstones and compaction need care | Cassandra, ScyllaDB, Keyspaces |
| Search index | Full-text search, relevance, facets, filters | Not a source of truth; feed it from the database and accept lag | OpenSearch, Elasticsearch |
| Time-series | Metrics and sensor data queried by time range | High-cardinality labels explode cost | Prometheus, InfluxDB, TimescaleDB |
| Graph | Queries that walk relationships many hops deep | Narrow use; most "graphs" fit relational tables | Neo4j, Neptune |
| Object storage | Files, images, video, backups, data-lake files | High per-request latency; no in-place edits | S3, GCS, Azure Blob |
| Analytical (columnar) | Aggregations over large history (OLAP) | Not for per-request traffic; load in batches or by stream | ClickHouse, Redshift, BigQuery, Snowflake |

Keep OLTP and OLAP apart: replicate to the warehouse through CDC or batch exports rather
than running reports against the primary. Use a connection pooler (PgBouncer, RDS Proxy)
when many app instances share a relational database.

### Replication

| Model | How it works | Trade-off |
|---|---|---|
| Single leader, async followers | One primary takes writes; replicas apply them shortly after | Replica lag: a user may not see their own write. Fix by returning the write's version or log position (LSN) to the client and reading from a replica only once it has replayed past it, otherwise from the primary. "Primary for N seconds after a write" is a heuristic that fails when lag exceeds N |
| Single leader, sync follower | A write commits once one follower has it too | No acknowledged write lost when failing over to that follower; slower writes; a slow follower stalls writes |
| Multi-leader | Several regions accept writes | Write conflicts need a resolution rule (last-writer-wins loses data; prefer per-record ownership or CRDTs) |
| Leaderless quorum | Writes go to W of N replicas, reads ask R | R + W > N makes read and write sets overlap, so a read normally sees the latest acknowledged write (N=3, W=2, R=2) |

### Partitioning (sharding)

- **Pick the key from the main access pattern:** high cardinality, even access, and the
  key most queries filter by (user ID, tenant ID, thread ID).
- **Hash partitioning** spreads load evenly but breaks range scans. **Range partitioning**
  keeps ranges together but concentrates load on the newest range when keys are
  time-ordered.
- **Consistent hashing** with virtual nodes means adding a node moves only about 1/N of
  the keys instead of reshuffling everything.
- **Hot partitions:** one celebrity, viral item or tenant can exceed one shard. Split hot
  keys with a suffix (write sharding), isolate big tenants, or cache in front.
- Cross-partition queries and transactions become expensive; design so the common paths
  stay inside one partition. Plan resharding from the start (more logical shards than
  physical nodes makes it a move, not a rewrite).

### ID generation

| Option | Use when | Watch out |
|---|---|---|
| Database sequence | One database, modest write rate | Single writer; IDs leak volume |
| UUIDv4 | Uncoordinated generation anywhere | Random values scatter B-tree inserts and hurt index locality |
| UUIDv7, ULID, Snowflake-style | Many writers and time-ordered IDs wanted | Embeds a timestamp; clock skew can reorder IDs slightly |
| Range allocation | Short, dense IDs (short links) without per-ID coordination | A crashed server wastes its block; the range service must be highly available |

---

## 4. Consistency and coordination

**CAP, stated correctly.** During a network partition, a replicated system must choose
between consistency (refuse or delay some requests) and availability (answer, possibly
with stale data). Partitions happen on any real network, so "pick two of three" is
misleading: the choice is C or A *when a partition happens*. **PACELC** adds the
everyday case: Else, with no partition, the choice is between Latency and Consistency.
That second trade-off is the one most designs face most of the time.

**Choose consistency per entity, not per system:**

| Data | Needs | Why |
|---|---|---|
| Money, balances, stock at checkout, seat holds, unique usernames, permissions | Strong (linearizable) | Stale reads cause double-spends, oversells or security holes |
| A user's own recent writes (profile edits, posts) | Read-your-writes | The user notices their own change missing; others don't |
| Chat messages within one conversation | Ordered per conversation | Order matters inside the conversation, not across conversations |
| Feeds, counters, likes, view counts, search results, recommendations | Eventual | Seconds of lag are invisible; exactness costs throughput |

**Contended updates (the oversell problem).** Prefer, in order:

1. An atomic conditional write: `UPDATE stock SET qty = qty - 1 WHERE id = ? AND qty > 0`.
2. Optimistic concurrency: a version column or ETag; retry on conflict.
3. A short pessimistic lock (`SELECT … FOR UPDATE`) for multi-row invariants.
4. A reservation with expiry: hold stock for N minutes during checkout; release on timeout.

**Idempotency.** Retries and at-least-once delivery mean every unsafe operation can arrive
twice. Give each one an idempotency key, store the key with the result, and return the
stored result on a repeat. Prefer operations that are naturally idempotent (set a value)
over ones that aren't (increment it).

**Coordination.** Use a consensus system (etcd, ZooKeeper, Consul) or the database for
leader election and leases rather than inventing one. A distributed lock alone is not
safe, because a holder can pause past its lease: pair it with a fencing token the
resource checks, or use a database constraint or conditional write instead. Split brain
is prevented by quorums and fencing, not by heartbeats alone.

**Distributed transactions.** Two-phase commit gives atomicity but blocks when the
coordinator fails; keep it inside one database system. Across services, use a saga with
compensating actions and the transactional outbox; see `../cloud-patterns/patterns.md`
§6–8.

**Time.** Don't order events across machines by wall-clock time. Use a sequence number
per entity, a single writer per key, or logical clocks.

---

## 5. Messaging

| Model | Semantics | Use for | Examples |
|---|---|---|---|
| Queue | Each message goes to one consumer; deleted when acknowledged | Distributing work: jobs, emails, image processing | SQS, RabbitMQ queues |
| Pub/sub | Each message goes to every subscriber | Fan-out of events to independent consumers | SNS, EventBridge, Google Pub/Sub |
| Log / stream | Ordered, retained, replayable; consumers track their own offset | Event streams, CDC, analytics, rebuilding state, very high throughput | Kafka, Kinesis, Pulsar, Redis Streams |

**Delivery semantics.** At-most-once can lose messages. At-least-once is the practical
default; pair it with idempotent consumers and the result is effectively once.
"Exactly once" holds only inside one system's boundary (Kafka transactions, for example);
side effects in the outside world, such as sending an SMS or charging a card, still need
idempotency keys.

**Ordering** holds only within a partition or message group. Partition by the entity
whose order matters (conversation ID, order ID). Needing global order is rare and caps
throughput at one consumer.

**Mechanics to get right:**

- Acknowledge after processing, not on receipt.
- Visibility timeout longer than the processing time; extend it for long jobs.
- Retries with exponential backoff and jitter; a dead-letter queue after N attempts, an
  alert on its depth, and a tested redrive path.
- Backpressure: bounded queues, alerts on consumer lag or oldest-message age, consumers
  that autoscale on backlog per worker (KEDA, SQS metrics).
- Priority with separate queues and worker pools, not a priority field in one queue.
  See `../cloud-patterns/patterns.md` §19–21.

| Tool | Pick when |
|---|---|
| SQS | Managed work queue with little to operate; FIFO queues for per-group order |
| SNS / EventBridge | Managed fan-out; EventBridge for content-based routing |
| Kafka / MSK / Kinesis | High-throughput ordered streams, replay, many consumer groups |
| RabbitMQ | Rich routing (topic, header exchanges), per-message acknowledgement, AMQP |
| Redis Streams / NATS | Lightweight, low-latency messaging where durability needs are modest |

---

## 6. APIs and client communication

| Style | Use when | Watch out |
|---|---|---|
| REST over HTTP | Public APIs, resource-shaped data, HTTP caching | Over- and under-fetching for complex screens |
| GraphQL | Many clients needing different shapes of the same data | Caching is harder; guard query depth and cost; N+1 resolvers |
| gRPC | Internal service-to-service calls, streaming, strict contracts | Browsers need a proxy; binary payloads are harder to debug |

**Real-time delivery to clients:**

| Option | Direction | Use when | Cost |
|---|---|---|---|
| Short polling | Client pulls | Updates every minute or slower are fine | Wasted requests; delay up to the interval |
| Long polling | Server answers when data arrives | Near-real-time where WebSockets are blocked | One held request per waiting client |
| Server-sent events | Server → client stream over HTTP | Live feeds, notifications, progress, token streaming | One-way; text only; reconnects built in |
| WebSockets | Both ways, persistent | Chat, collaboration, games, live location | A stateful connection tier: a registry of which gateway holds which user, and a fan-out path between gateways |
| Webhooks | Server → server push | Notifying partner systems | Sign payloads, retry with backoff, let receivers dedupe |
| Mobile push (APNs, FCM) | Platform → device | Reaching apps in the background | Best-effort delivery; provider rate limits |

**Every API should have:** timeouts on every outbound call; idempotency keys on unsafe
operations that clients may retry (POST, payments); cursor-based pagination for large or
changing lists (offset pagination skips and repeats rows as data changes); rate limits
that return `429` with `Retry-After`; a versioning rule; request size limits; and one
error model.

---

## 7. Rate limiting and load protection

| Algorithm | Behaviour | Use when | Watch out |
|---|---|---|---|
| Token bucket | Tokens refill at rate r up to capacity b; each request takes one | Default for per-client limits: allows bursts up to b, averages r. GCRA is the same limit stored as one timestamp per key | Tune b to the burst you'll accept |
| Leaky bucket | Requests drain at a constant rate; excess queues or drops | Smoothing traffic to a fragile downstream | Adds queueing delay; no bursts |
| Fixed window counter | Count per clock window (per minute) | Cheap, coarse quotas | Up to 2× the limit across a window boundary |
| Sliding window log | Store a timestamp per request; count those in the window | Exact limits at low volume | Memory grows with the limit |
| Sliding window counter | Weighted blend of the current and previous windows | Good accuracy at constant memory when bursts aren't wanted | Approximate at the edges |

**Where to limit:** at the edge or WAF for abusive IPs; at the API gateway per key or
plan; in each service to protect its own dependencies; per tenant for fairness.

**Distributed counters.** Keep counters in a shared store (Redis) and update them
atomically: one Lua script per check (token bucket or sliding window), or `INCR` plus
`EXPIRE` in one transaction, so app servers can't race. Key by client and window
(`ratelimit:{api_key}:{window}`); with Redis Cluster, hash-tag the client ID so its keys
share a slot. The check sits on every request, so its latency budget is about a
millisecond. At very high rates, keep approximate local buckets per instance and sync
them periodically.

Details that matter:

- **Authenticate the key before counting it**, or random keys fill the store; limit
  unauthenticated traffic by IP.
- **Cache denials locally:** when the store says "retry after X", the instance rejects
  that key itself until X, so an abusive client costs one store call per instance per
  window, not one per request.
- **Call the store with a short timeout (~10 ms), no inline retries, and a circuit
  breaker.** Retrying thousands of checks a second against a recovering store turns a
  blip into an outage.
- **Hold limits config in memory** in each instance, refreshed every minute or so; never
  read it from a database per request.
- **Roll out in shadow mode:** log decisions without rejecting for a week or two, tune
  rates and bursts against real traffic, then enforce one tier at a time.

**When the counter store is down, decide per route:**

- **Fail open** (allow the request) where availability matters more than precise limits.
  Fall back to per-instance buckets sized at rate × headroom ÷ number of instances
  (headroom 1.5–2× so the fallback errs generous; burst at least 1; recompute as
  instances scale), and keep per-instance load shedding as a backstop.
- **Fail closed** (reject) where the limit protects money or security: login and OTP
  endpoints, expensive paid operations, abuse-prone writes.
- **Outbound limiters that guard a provider's quota err low instead:** fall back to about
  80% of the quota ÷ number of instances, since going over only earns 429s from the
  provider.

Return `429 Too Many Requests` with `Retry-After` and limit headers so clients back off
with jitter. Monitor the limiter itself: decisions by tier, store latency, breaker state,
and a jump in the share of rejected requests (a bad limits rollout rejects legitimate
traffic without raising a single 5xx).

**Beyond rate limits:** load shedding (drop the lowest-priority work first when
saturated), admission control and bounded queues, per-tenant quotas, and circuit breakers
on dependencies (`../cloud-patterns/patterns.md` §2).

---

## 8. Failure handling and operations

- **Timeouts:** set one on every call, from a latency budget for the whole request
  (if the API promises 300 ms, three sequential calls can't each wait 1 s).
- **Retries:** only for idempotent operations; capped, with exponential backoff and
  jitter, and a retry budget (retries no more than ~10% of calls) so retries can't
  multiply an outage.
- **Isolation:** circuit breakers and bulkheads (`../cloud-patterns/patterns.md` §2,
  `../well-architected/patterns.md`), separate pools for critical and bulk work.
- **Graceful degradation:** decide in advance what to drop when a dependency fails:
  serve stale cache, hide recommendations, queue writes for later.
- **Redundancy:** spread every tier across zones; multi-region only when the RTO/RPO or
  latency targets demand it (active-passive vs active-active:
  `../well-architected/decisions.md` §6).
- **Deploys:** rolling, blue-green or canary with automatic rollback on SLO burn; feature
  flags to separate deploy from release (DevOps lens).
- **Observability:** golden signals per service, RED per endpoint, USE per resource, SLOs
  with burn-rate alerts, a runbook linked from every alert
  (`../platform-engineering/frameworks.md`, SRE Principles).
- **Capacity:** load test to find each component's knee; keep headroom to survive a zone
  loss at peak; alert on saturation before it hurts.

---

## 9. Trade-off pairs

State the cost of every choice: "this gives X, and we give up Y."

| Trade-off | Choose the first when | Choose the second when |
|---|---|---|
| Consistency vs availability (during a partition) | Wrong answers cost more than no answer (money, stock, auth) | A stale answer beats an error (feeds, catalogs, profiles) |
| Consistency vs latency (normal operation, PACELC) | Correctness matters more than milliseconds | Reads can lag by seconds |
| SQL vs NoSQL | Relationships, transactions, unknown future queries | Known access patterns at very high scale, flexible schema |
| Normalized vs denormalized | Writes dominate; one place to update | Reads dominate; precompute the shape each screen needs |
| Fan-out on write (push) vs on read (pull) | Readers far outnumber writers and follower counts are bounded | Writers have huge audiences (celebrities); combine the two |
| Sync vs async | The caller needs the result to continue | The work can finish later, is slow, or must survive spikes |
| Stateless vs stateful services | Default: scale out, replace freely | Long-lived connections or in-memory state are the product (chat gateways, game servers) |
| Cache vs no cache | Read-heavy, latency-sensitive, expensive queries | Write-heavy, must-be-exact, or simplicity wins |
| Monolith vs services | Small team, young domain, fast iteration | Teams blocking each other, parts with very different scaling needs |
| Build vs managed service | A core differentiator, or unusual requirements | Commodity capability; the team's time is better spent elsewhere |

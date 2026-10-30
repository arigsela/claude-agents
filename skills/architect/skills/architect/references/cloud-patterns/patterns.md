# Cloud Design Patterns - Detailed Reference

Sources: AWS Prescriptive Guidance cloud design patterns (§1–14). §15–21 follow the Azure Architecture Center cloud design patterns catalog, with AWS implementations.

---

## 1. Anti-Corruption Layer (ACL)

**Category**: Migration
**Intent**: Mediation layer that translates domain model semantics between systems during migration.

### When to Use
- Monolithic apps communicating with migrated microservices that have different domain models
- Two systems with different semantics where modifying one is impractical
- Quick adapter needed to bridge old and new interfaces
- Application communicating with external systems

### How It Works
```
Monolith (Caller) → ACL (Adapter/Facade) → API Gateway → Microservice
```

The ACL translates calls from the old interface to the new microservice interface, enabling transparent routing without changing the calling code.

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Team dependencies | Decouples callees, avoids coordinated changes across teams |
| Single point of failure | Add retry + circuit breaker; monitor with alarms and logging |
| Technical debt | Document as interim vs. long-term; decommission after migration |
| Latency | Interface conversion adds delay; test performance before production |
| Scaling | Can become bottleneck under high load; design to scale horizontally |

### AWS Implementation
- ACL implemented as class within monolith or as independent service
- API Gateway as the endpoint for the migrated microservice
- Lambda or ECS for the microservice compute

### Related Patterns
- Strangler Fig (migration wrapper)
- Circuit Breaker (resilience for ACL calls)

---

## 2. Circuit Breaker

**Category**: Resilience
**Intent**: Prevent cascading failures by stopping calls to failing services, then auto-recovering when they heal.

### When to Use
- Caller service makes calls likely to fail
- Callee exhibits high latency causing timeouts
- Synchronous calls to unavailable or high-latency services

### How It Works - Three States

| State | Behavior |
|-------|---------|
| **CLOSED** | Normal operation; all calls pass through to callee |
| **OPEN** | Circuit tripped; calls fail immediately without reaching callee |
| **HALF-OPEN** | Testing phase; periodic calls check if callee has recovered |

**Flow**: Failures detected → threshold exceeded → circuit OPEN → immediate failure responses → periodic retry → success detected → circuit CLOSED

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Service agnostic | Implement in API-driven, microservice-agnostic way |
| Callee recovery | Callee can optionally update circuit to CLOSED when healthy |
| Multithreaded | First failed call sets expiration; prevent endless timeout extension |
| Manual control | Admins should force open/close circuits by updating timeout values |
| Observability | Log all failed calls when circuit is open for monitoring |

### AWS Implementation
- **Step Functions**: State machine implementing circuit breaker logic
- **DynamoDB**: Stores circuit status with TTL for automatic expiry
- **ElastiCache (Redis)**: Alternative in-memory store for better performance
- **Lambda**: Executes actual service calls

### Related Patterns
- Retry with Backoff (for transient errors before circuit trips)

---

## 3. Retry with Backoff

**Category**: Resilience
**Intent**: Transparently retry failed operations with exponentially increasing wait times.

### When to Use
- Services returning 429 (Too Many Requests)
- Transient network connectivity issues
- Temporarily unavailable services where uncontrolled retries could cause degradation

### How It Works
```
Attempt 1: Immediate
Attempt 2: Wait base_delay
Attempt 3: Wait base_delay * multiplier
Attempt 4: Wait base_delay * multiplier^2
...until max_retries reached → return error
```

Example with 3s base, 1.5x multiplier:
- Retry 1: 3s delay
- Retry 2: 4.5s delay
- Retry 3: 6.75s delay

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Idempotency | Operations MUST be idempotent; multiple calls = same effect |
| Network bandwidth | Excessive retries consume bandwidth and slow response |
| Non-transient errors | For permanent failures, use Circuit Breaker instead |
| Timeout impact | Exponential backoff increases overall timeout duration |

### AWS Implementation
- **Step Functions**: Native retry with configurable backoff multiplier
- **Lambda Powertools**: Built-in retry utilities
- **SDK retry**: AWS SDK has built-in retry with backoff for API calls

### Related Patterns
- Circuit Breaker (escalation when retries fail)

---

## 4. Publish-Subscribe (Pub-Sub)

**Category**: Messaging
**Intent**: Decouple message senders from receivers using an intermediary message broker.

### When to Use
- Single message triggers different workflows in parallel
- Broadcasting messages to multiple subscribers without real-time response needs
- System can tolerate eventual consistency
- Services use different languages, protocols, or platforms

### How It Works
```
Publisher → Message Broker (Topic) → Subscriber 1
                                   → Subscriber 2
                                   → Subscriber 3
```

The broker tracks subscriptions, copies messages to all output channels, and handles delivery.

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Delivery guarantees | At-least-once to each subscriber; SNS FIFO adds ordering and 5-minute deduplication, but side effects outside AWS still need idempotency keys |
| Message ordering | Not guaranteed by default; use FIFO topics for ordering |
| Eventual consistency | Delay between publish and consume causes temporary inconsistency |
| Idempotency | Consumers must handle duplicate messages |
| Dead-letter queues | Handle undeliverable messages with DLQs |
| TTL | Messages expire if not processed within time period |

### AWS Implementation

**Amazon SNS** - Managed pub-sub:
- Standard Topics: unlimited messages/sec, best-effort ordering
- FIFO Topics: strict ordering and deduplication, lower throughput than Standard (check current quotas)

**Amazon EventBridge** - Complex routing:
- Content-based routing and filtering
- Multiple producers across protocols
- Event rules defining subscriber behaviors
- Schema registry for event structure

### Related Patterns
- Event Sourcing, Saga Choreography, Scatter-Gather

---

## 5. Scatter-Gather

**Category**: Messaging
**Intent**: Broadcast requests to multiple recipients in parallel and aggregate responses.

### When to Use
- Data aggregation from multiple APIs (e.g., flight/hotel booking across providers)
- Parallel queries across multiple data sources
- Load balancing by distributing requests across recipients
- Map-reduce style parallel processing
- Write-heavy workloads distributed across partition keys

### How It Works

**Two phases:**
1. **Scatter**: Broadcast requests to multiple recipients in parallel
2. **Gather**: Collect, filter, and combine responses into unified output

**Two implementation approaches:**

| Approach | Description | Coupling |
|----------|------------|---------|
| Scatter by Distribution | Controller assigns tasks to known recipients | Tight - controller knows all recipients |
| Scatter by Auction | Requests published to topic; recipients self-subscribe | Loose - add recipients without changing controller |

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Response time | Limited by slowest recipient; implement timeouts |
| Partial responses | Some recipients may timeout; communicate incomplete results |
| Fault tolerance | Multiple parallel recipients increase failure risk; add redundancy |
| Data consistency | Multi-recipient processing risks inconsistency |
| Scale limits | Network overhead increases with more nodes |

### AWS Implementation

**Scatter by Distribution:**
- Step Functions (Parallel state) → Lambda functions → S3 (results)

**Scatter by Auction:**
- SNS (topic publish) → ECS/EKS services → SQS (response queue) → Aggregator

### Related Patterns
- Pub-Sub (for the scatter phase)

---

## 6. Saga Orchestration

**Category**: Transactions
**Intent**: Central coordinator manages distributed transactions across multiple services with compensatory rollback.

### When to Use
- Data integrity needed across multiple data stores
- NoSQL databases lacking 2PC/ACID transactions
- Complex multi-step business processes requiring rollback

### How It Works
```
Orchestrator (Step Functions)
  ├── T1: Place Order → success
  ├── T2: Update Inventory → success
  ├── T3: Make Payment → FAILURE
  │   ├── C3: Revert Payment
  │   ├── C2: Revert Inventory
  │   └── C1: Remove Order
  └── Return: Failure
```

The orchestrator coordinates the sequence and triggers compensatory transactions on failure.

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Complexity | Compensatory transactions add maintenance overhead |
| Eventual consistency | Sequential processing = eventual, not strong consistency |
| Idempotency | Participants must handle repeated execution |
| Transaction isolation | Lack of ACID isolation; use semantic locking |
| Observability | Complex debugging as participants increase |
| Single point of failure | Mitigated by Step Functions HA |

### AWS Implementation
- **Step Functions**: Orchestrator with built-in fault tolerance, retries, visual monitoring
- **Lambda**: Individual service functions (order, inventory, payment)
- **DynamoDB/RDS**: Per-service data stores
- **API Gateway**: Entry point

### When to Choose Over Choreography
- > 5 services in the transaction
- Complex rollback logic
- Need centralized monitoring and control
- Team prefers explicit workflow definition

### Related Patterns
- Saga Choreography (alternative approach)
- Transactional Outbox (atomic events)

---

## 7. Saga Choreography

**Category**: Transactions
**Intent**: Event-driven distributed transactions where services react to events without central coordination.

### When to Use
- Data integrity across distributed stores
- Want to avoid single point of failure (no central orchestrator)
- Saga participants are independent, loosely coupled services
- Communication between bounded contexts in a domain

### How It Works
```
Order Service → "Order placed" event → EventBridge
  → Inventory Service → "Inventory updated" event → EventBridge
    → Payment Service → "Payment processed" event → EventBridge
      → Success

On failure (payment fails):
  Payment Service → "Payment failed" event
    → Inventory Service → revert → "Inventory reverted" event
      → Order Service → remove order → Consistent state
```

Each service reacts to events and publishes its own events, creating a chain.

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Complexity | Harder to manage as services increase |
| Cyclic dependencies | Participants consuming each other's messages → potential deadlocks |
| Dual writes | Atomic DB update + event publish is hard; use Transactional Outbox |
| Observability | Distributed flow difficult to trace end-to-end |
| Resilience | Harder to implement global timeouts vs. orchestration |

### AWS Implementation
- **EventBridge**: Custom event buses per service domain
- **Lambda**: Service implementations
- **EventBridge Rules**: Route events to appropriate services
- **DynamoDB/RDS**: Per-service data stores

### When to Choose Over Orchestration
- Few participants (< 5 services)
- Simple transaction flows
- Want maximum decoupling
- Teams prefer autonomous event-driven approach

### Related Patterns
- Transactional Outbox (solves dual write problem)
- Event Sourcing (event persistence)
- Retry with Backoff (transient failure handling)

---

## 8. Transactional Outbox

**Category**: Transactions
**Intent**: Ensure atomicity when an application needs to both update a database AND publish an event.

### The Dual Write Problem
```
Service updates DB → success
Service publishes event → FAILURE → downstream unaware = inconsistency
```

### When to Use
- Event-driven apps where DB updates initiate event notifications
- Need atomicity across database + messaging operations
- Implementing event sourcing pattern

### How It Works

**Option 1: Outbox Table (Relational DB)**
```
Single Transaction:
  1. Write to Flight table
  2. Write to Outbox table
  → Both succeed or both fail (atomic)

Background process:
  Poll Outbox table → Publish to SQS → Delete from Outbox
```

**Option 2: Change Data Capture (DynamoDB)**
```
Write to DynamoDB table
  → DynamoDB Streams auto-captures change
    → Lambda processes stream record
      → Publishes to SQS
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Duplicate messages | Consumers must be idempotent |
| Message order | Maintain order matching DB update sequence |
| Transaction rollback | Never send events if transaction rolls back |
| Cross-service | Use Saga pattern for multi-service transactions |

### AWS Implementation

| Approach | Services |
|----------|----------|
| Outbox Table | RDS + Lambda (poller) + SQS |
| CDC | DynamoDB + DynamoDB Streams + Lambda + SQS |
| CDC (Kinesis) | DynamoDB + Kinesis Data Streams + Lambda + SQS |

### Related Patterns
- Saga Choreography / Orchestration
- Event Sourcing

---

## 9. Event Sourcing

**Category**: Data
**Intent**: Store all state changes as an immutable, append-only sequence of events.

### When to Use
- Immutable history required for tracking changes
- Polyglot data projections from single source of truth
- Point-in-time state reconstruction needed
- Write-intensive workloads without real-time read requirements
- Audit data required for compliance
- What-if analysis via replaying modified events

### How It Works
```
Command → Event Store (append-only, chronological)
  ├── Materialized View (Aurora) ← for read queries
  ├── Archive (S3) ← for compliance/audit
  └── Event Replay → reconstruct state at any point
```

**Three ways to derive current state:**
1. Event Aggregation (combine related events)
2. Materialized Views (compute/summarize)
3. Event Replay (replay from beginning or snapshot)

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Concurrency | Versioning, timestamps, or conflict resolution for simultaneous updates |
| Eventual consistency | CQRS/materialized views have latency |
| Event store size | Archive periodically to S3 |
| Replay performance | Use snapshots to avoid replaying entire history |
| Event ordering | Use FIFO queues for at-most-once ordered delivery |
| Event versioning | Include version fields; handle different versions during replay |

### AWS Implementation
- **Kinesis Data Streams**: Event store (high-throughput, real-time)
- **EventBridge / MSK**: Alternative event stores
- **S3**: Archive for compliance and audit
- **Aurora**: Materialized views for read operations
- **Lambda**: Event processing and transformation
- **API Gateway**: Entry point for commands

### Related Patterns
- CQRS (command/query separation)
- Transactional Outbox
- Pub-Sub

---

## 10. Hexagonal Architecture (Ports & Adapters)

**Category**: Architecture
**Intent**: Decouple business logic from infrastructure through ports (interfaces) and adapters (implementations).

### When to Use
- Need fully testable components without infrastructure dependencies
- Multiple clients use the same domain logic
- UI and database require periodic technology refreshes
- Multiple input providers and output consumers

### How It Works
```
External Actor → Adapter → Port → Domain Logic → Port → Adapter → External System

Example:
API Gateway → Lambda Handler (adapter) → Input Port → Business Logic → Output Port → DynamoDB Adapter → DynamoDB
```

**Ports**: Technology-agnostic interfaces defining how to interact with the application
**Adapters**: Technology-specific implementations that plug into ports

### Key Considerations

| Concern | Guidance |
|---------|---------|
| DDD alignment | Works especially well with Domain-Driven Design |
| Complexity | Requires disciplined separation of concerns |
| Maintenance | Adapter code justified only if multiple input/output sources |
| Latency | Additional adapter layers may add latency |

### AWS Implementation
- **API Gateway**: External adapter (input)
- **Lambda**: Contains business logic separated from infrastructure
- **DynamoDB**: Data adapter (output)
- Business logic testable without any AWS dependencies

### Benefits
- Swap databases without touching business logic
- Unit test business logic in isolation with mock adapters
- Change UI technology without affecting core logic

---

## 11. Strangler Fig

**Category**: Migration
**Intent**: Incrementally migrate a monolith to microservices by routing traffic through a proxy layer.

### When to Use
- Gradual monolith-to-microservices migration
- Big-bang rewrite is too risky
- Business needs continuous feature delivery during migration
- Minimizing user impact is critical

### How It Works

**Phase 1**: Add proxy layer (API Gateway) routing all traffic to monolith
**Phase 2**: Extract features as microservices; proxy routes selectively
**Phase 3**: Add ACL for monolith-to-microservice calls
**Phase 4**: Sync data between old and new stores
**Phase 5**: Decommission monolith

```
Phase 1: Client → API Gateway → Monolith (all traffic)
Phase 2: Client → API Gateway → Monolith (old features)
                              → Microservice A (migrated)
Phase 5: Client → API Gateway → Microservice A
                              → Microservice B
                              → Microservice C
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Code access | Must have monolith source code for ACL implementation |
| Domain clarity | Use DDD/event storming to define service boundaries first |
| Proxy as SPOF | Add circuit breaker; monitor for timeout/thread pool issues |
| Data consistency | Use queuing + sync agent; eventual consistency is tactical |
| Service communication | Sync calls need circuit breaker; async uses event queues |

### AWS Implementation
- **API Gateway**: Proxy layer / intelligent router
- **Lambda / ECS**: Microservice compute
- **DynamoDB / ElastiCache / RDS**: Polyglot persistence per service
- **S3**: Static asset hosting

### Related Patterns
- ACL (interface translation within monolith)
- API Routing (exposing migrated services)
- Circuit Breaker (resilience for proxy)

---

## 12-14. API Routing Patterns

### Hostname Routing

**Intent**: Each API gets its own subdomain.
```
billing.api.example.com → Billing Service
users.api.example.com → Users Service
```

| Pros | Cons |
|------|------|
| Straightforward and scalable | Consumers must remember different hostnames |
| Complete team isolation | DNS management burden per service |
| Deployment flexibility per region/version | Client SDK overhead for multi-hostname |

**AWS Services**: API Gateway, AppSync, ALB, EC2

### Path Routing

**Intent**: All APIs under one hostname, differentiated by URI path.
```
api.example.com/billing → Billing Service
api.example.com/users → Users Service
```

| Approach | Best For | Trade-off |
|----------|----------|-----------|
| NGINX reverse proxy | High volume (100K+ TPS) | Requires infrastructure management |
| API Gateway | Medium volume with auth/throttling | Higher cost at scale |
| CloudFront + Lambda@Edge | Caching + custom routing logic | 250 origin limit, propagation delay |

### HTTP Header Routing

**Intent**: Route based on custom HTTP headers.
```
x-service-action: get-billing → Billing Service
```

| Pros | Cons |
|------|------|
| Easy configuration | Requires client control over headers |
| Flexible, non-intrusive | Proxy/CDN/LB header size limits |
| Combinable with other routing | Not suitable for public APIs |

**Best practice**: Use header routing in combination with path routing for robust APIs.

---

## 15. CQRS (Command Query Responsibility Segregation)

**Category**: Data
**Intent**: Separate the model that changes data from the model(s) that read it, so each can be shaped and scaled for its own job.

### When to Use
- Read and write shapes differ a lot (writes are small commands; reads are wide, joined or searched views)
- Read load far exceeds write load and needs its own scaling
- Several read views of the same data (search, reporting, per-screen projections)
- Often paired with Event Sourcing, but works without it

### How It Works
```
Command → Write model (source of truth) → change events / CDC → Projector → Read store(s)
Query   → Read store (denormalized, per use case)
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Eventual consistency | Read stores lag the write side; return the new state from the command, or read from the write side, when a user must see their own change |
| Projection rebuilds | Keep the event or change history so a read store can be rebuilt from scratch |
| Complexity | More moving parts; don't apply it to simple CRUD screens |
| Idempotent projectors | Events can arrive twice or out of order. With full-state events, keep the highest version per entity and ignore older ones. With incremental events, apply only the next contiguous version: consume from a stream partitioned by entity ID so order holds, and on a gap buffer or refetch from the write side rather than skipping ahead |

### AWS Implementation
- Write side: Aurora or DynamoDB
- Change feed: DynamoDB Streams, DMS or Debezium CDC from Aurora, or an outbox table → EventBridge; Aurora zero-ETL integration to Redshift for reporting views
- Read side: OpenSearch (search), DynamoDB tables per access pattern, Redshift (reporting)

### Related Patterns
- Event Sourcing, Transactional Outbox, Materialized views

---

## 16. Sidecar

**Category**: Architecture
**Intent**: Run a cross-cutting capability as a separate process or container next to the application, sharing its lifecycle and network.

### When to Use
- The same concern is needed across services in different languages (proxying, mTLS, log or telemetry shipping, secret fetching, config reload)
- The application can't or shouldn't be changed to add the capability
- The capability must be versioned and rolled out independently of the app

### How It Works
```
Pod / task
├── app container        ←→ localhost
└── sidecar container    → network, logs, secrets, telemetry
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Resource overhead | Every replica pays for the sidecar's CPU and memory; size it |
| Startup and shutdown order | Use Kubernetes native sidecars (init containers with `restartPolicy: Always`) so the sidecar starts first and stops last |
| Latency | An extra local hop per call; small but measurable for chatty services |
| Alternatives | Sidecarless (ambient, node-level) service mesh, or a library when all services share a language |

### AWS Implementation
- EKS pods or ECS task definitions with multiple containers
- Common sidecars: Envoy/Istio proxy, AWS Distro for OpenTelemetry collector, Fluent Bit, Secrets Store CSI provider

### Related Patterns
- Ambassador, Anti-Corruption Layer

---

## 17. Ambassador

**Category**: Architecture
**Intent**: A sidecar that acts as an out-of-process client proxy for calls to remote services, adding resilience, security and telemetry without changing the caller.

### When to Use
- Legacy or third-party code that can't be changed needs retries, timeouts, circuit breaking, TLS or auth on its outbound calls
- One consistent client policy across services written in different languages
- Routing outbound calls by environment or version (canary, region)

### How It Works
```
App → localhost:port → Ambassador (retries, timeouts, mTLS, metrics) → Remote service
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Latency | Adds a hop; avoid for latency-critical paths that can use a client library |
| Retry ownership | Retries in both the app and the ambassador multiply load; keep them in one place |
| Scope creep | Keep it a thin proxy; business logic belongs in the service |
| At scale | A service mesh applies ambassador behaviour to every service centrally |

### AWS Implementation
- Envoy as a sidecar in EKS or ECS
- VPC Lattice for service-to-service routing, auth and observability without sidecars

### Related Patterns
- Sidecar, Circuit Breaker, Retry with Backoff

---

## 18. Backends for Frontends (BFF)

**Category**: Routing
**Intent**: A separate API layer per client experience (web, mobile, partner) that aggregates and shapes backend data for that client.

### When to Use
- Clients need very different payloads, call patterns or auth flows from the same services
- Mobile clients suffer from chatty calls or oversized responses
- Separate frontend teams want to change their API without coordinating with every other client

### How It Works
```
Web app    → Web BFF    ┐
Mobile app → Mobile BFF ├→ Domain services
Partners   → Public API ┘
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Ownership | The frontend team owns its BFF |
| Duplication | Shared logic creeps into several BFFs; keep business rules in the domain services |
| Number of BFFs | One per distinct experience, not one per screen or device model |
| Alternative | A single GraphQL gateway when clients differ mainly in which fields they need |

### AWS Implementation
- API Gateway + Lambda, or a container service, per client
- AWS AppSync (GraphQL) as a single flexible gateway

### Related Patterns
- Path Routing, Scatter-Gather, Anti-Corruption Layer

---

## 19. Queue-Based Load Leveling

**Category**: Messaging
**Intent**: Put a queue between the producers of work and the service that does it, so the service processes at its own sustainable rate and spikes wait in the queue instead of overloading it.

### When to Use
- Traffic is bursty but the work can finish a little later (seconds to minutes)
- A downstream (database, third-party API) has a hard throughput limit
- Requests time out or the service falls over during peaks

### How It Works
```
Producers (bursty) → Queue (absorbs the spike) → Service at a steady rate → Result / status
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Async contract | Callers get "accepted" plus a way to check status or a callback; not for work the caller must wait on |
| Queue growth | Alert on queue depth and oldest-message age; a queue that never drains is an outage in slow motion |
| Consumer scaling | Scale workers on backlog per worker, capped at what the downstream can take |
| Expiry | Drop or divert work that is no longer useful by the time it would be processed |

### AWS Implementation
- SQS in front of Lambda (cap the rate with the event source mapping's maximum concurrency) or ECS/EKS workers scaled by KEDA on queue depth
- Kinesis or MSK when order or replay matters

### Related Patterns
- Competing Consumers, Priority Queue, Retry with Backoff

---

## 20. Competing Consumers

**Category**: Messaging
**Intent**: Several workers pull from the same queue so work is processed in parallel and throughput scales by adding workers.

### When to Use
- Independent work items that can be processed in any order
- Throughput must scale with load, and losing one worker must not stop processing

### How It Works
```
Queue → Worker 1
      → Worker 2   (each message goes to exactly one worker at a time)
      → Worker N
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Ordering | Lost across workers; when order matters per entity, use message groups (SQS FIFO) or partitions (Kafka consumer groups) keyed by that entity |
| Duplicates | A worker can crash after doing the work but before acknowledging; make processing idempotent |
| Visibility timeout | Longer than the processing time, or extended while working, or another worker picks the message up too |
| Poison messages | Cap attempts and move failures to a DLQ, alerting on its depth |

### AWS Implementation
- SQS with an autoscaled worker fleet (ECS, EKS with KEDA, Lambda event source mapping)
- Kinesis or MSK consumer groups for ordered, per-partition parallelism

### Related Patterns
- Queue-Based Load Leveling, Priority Queue, Publish-Subscribe

---

## 21. Priority Queue

**Category**: Messaging
**Intent**: Process urgent work ahead of bulk work by giving each priority its own queue and consumers.

### When to Use
- Urgent and bulk work share a pipeline (one-time passcodes and marketing campaigns, paid and free tiers, interactive and batch jobs)
- Bulk bursts must never delay urgent work

### How It Works
```
High priority → Queue H → dedicated workers (always reserved)
Low priority  → Queue L → workers that scale with spare capacity
```

### Key Considerations

| Concern | Guidance |
|---------|---------|
| Separate queues | Most managed queues (SQS included) have no per-message priority; use one queue per level |
| Starvation | Reserve a minimum share for low priority, or it may never run during sustained load |
| Classification | Define what qualifies as high priority, or everything drifts into it |
| Shared limits | Separate queues don't help if both lanes hit the same downstream quota; split or reserve that too |

### AWS Implementation
- One SQS queue per priority with separate consumer pools, or one pool polling with weighted preference
- EventBridge rules or SNS filter policies to route messages to the right queue by type

### Related Patterns
- Queue-Based Load Leveling, Competing Consumers

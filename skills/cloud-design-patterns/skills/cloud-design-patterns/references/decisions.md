# Cloud Design Patterns - Decision Trees

## 1. Pattern Selection by Challenge

```
What is the client's primary challenge?
│
├── Migrating from monolith to microservices
│   ├── How many services to extract?
│   │   ├── 1-3 services → Strangler Fig + ACL
│   │   ├── Many services → Strangler Fig + ACL + Path Routing
│   │   └── Full decomposition → Strangler Fig + ACL + Hexagonal Architecture
│   └── Data migration needed?
│       ├── Yes → Add Transactional Outbox for sync
│       └── No (shared DB for now) → Phase data later
│
├── Distributed transaction consistency
│   ├── How many services in the transaction?
│   │   ├── 2-4 services → Saga Choreography
│   │   ├── 5+ services → Saga Orchestration
│   │   └── Complex rollback logic → Saga Orchestration
│   ├── Need atomic DB + event?
│   │   └── Yes → Add Transactional Outbox
│   └── Need audit trail?
│       └── Yes → Add Event Sourcing
│
├── Service-to-service resilience
│   ├── What type of failure?
│   │   ├── Transient (network blips, throttling) → Retry with Backoff
│   │   ├── Sustained (service down) → Circuit Breaker
│   │   └── Both → Retry with Backoff + Circuit Breaker
│   └── Call pattern?
│       ├── Synchronous → Circuit Breaker (mandatory)
│       └── Asynchronous → Pub-Sub with DLQ
│
├── Need async event-driven communication
│   ├── One-to-many broadcasting → Pub-Sub (SNS or EventBridge)
│   ├── Parallel processing + aggregation → Scatter-Gather
│   ├── Complex routing rules → EventBridge
│   └── Simple fanout → SNS + SQS
│
├── Need full audit / compliance
│   └── Event Sourcing + S3 archival
│
├── Testability / tech lock-in concerns
│   └── Hexagonal Architecture (ports & adapters)
│
└── API strategy for microservices
    ├── Team autonomy is priority → Hostname Routing
    ├── Developer simplicity is priority → Path Routing
    └── Advanced routing needs → HTTP Header Routing (+ Path)
```

---

## 2. Saga Pattern Selection

```
Need distributed transactions?
│
├── How many services participate?
│   ├── 2-4 → Consider Choreography
│   └── 5+ → Prefer Orchestration
│
├── Need centralized monitoring?
│   ├── Yes → Orchestration (Step Functions)
│   └── No → Choreography (EventBridge)
│
├── Rollback complexity?
│   ├── Simple compensations → Choreography OK
│   └── Complex / conditional rollback → Orchestration
│
├── Team structure?
│   ├── Single team owns all services → Orchestration (simpler to manage)
│   └── Multiple teams, autonomous → Choreography (decoupled)
│
└── Observability requirements?
    ├── End-to-end workflow visibility → Orchestration (Step Functions console)
    └── Per-service event visibility → Choreography (EventBridge + X-Ray)
```

### Comparison Table

| Dimension | Orchestration | Choreography |
|-----------|--------------|--------------|
| Coordination | Central (Step Functions) | Distributed (EventBridge) |
| Coupling | Medium (orchestrator knows all) | Low (services know only events) |
| Complexity (few services) | Overkill | Right-sized |
| Complexity (many services) | Manageable | Hard to trace |
| Failure handling | Centralized | Per-service |
| Monitoring | Visual workflow | Distributed traces |
| Single point of failure | Orchestrator (mitigated by SF HA) | None |
| Adding services | Update orchestrator | Add subscriber |

---

## 3. API Routing Selection

```
How should microservices be exposed?
│
├── Team structure?
│   ├── Each team fully owns their service → Hostname Routing
│   │   (billing.api.example.com)
│   └── Centralized API team → Path Routing
│       (api.example.com/billing)
│
├── Client type?
│   ├── External / public consumers → Path Routing (one URL to remember)
│   ├── Internal services → Hostname Routing (full isolation)
│   └── Controlled clients (mobile app) → Header Routing possible
│
├── Traffic volume?
│   ├── < 10K TPS → API Gateway (path routing)
│   ├── 10K-100K TPS → CloudFront + Lambda@Edge (path routing)
│   └── > 100K TPS → NGINX reverse proxy (path routing)
│
└── Advanced routing needs?
    ├── A/B testing, canary → CloudFront + Lambda@Edge
    ├── Auth, throttling, usage plans → API Gateway
    └── Simple reverse proxy → ALB or NGINX
```

---

## 4. Messaging Pattern Selection

```
How should services communicate?
│
├── Communication style?
│   ├── Request-response (sync)
│   │   ├── Direct call → REST/gRPC + Circuit Breaker
│   │   └── Via proxy → API Gateway + Retry
│   └── Event-driven (async)
│       ├── One publisher, many subscribers → Pub-Sub (SNS)
│       ├── Complex routing rules → EventBridge
│       ├── Parallel processing, aggregate results → Scatter-Gather
│       └── Streaming / high throughput → Kinesis Data Streams
│
├── Delivery guarantees needed?
│   ├── At-most-once → SNS Standard
│   ├── At-least-once → SQS Standard
│   ├── Exactly-once → SQS FIFO / SNS FIFO
│   └── Ordered → FIFO queues/topics
│
├── Message persistence needed?
│   ├── Yes (audit, replay) → Event Sourcing (Kinesis + S3)
│   └── No (fire-and-forget) → SNS Standard
│
└── Dead letter handling?
    └── Always use DLQ with SQS/SNS for failed messages
```

---

## 5. Resilience Pattern Selection

```
What failure mode are you handling?
│
├── Transient failure (network glitch, 429 throttle)
│   └── Retry with Backoff
│       ├── AWS SDK built-in retry → for AWS API calls
│       ├── Step Functions retry → for workflow steps
│       └── Application-level → for custom service calls
│
├── Sustained failure (service down, high latency)
│   └── Circuit Breaker
│       ├── Step Functions + DynamoDB → serverless implementation
│       └── Application library → in-process implementation
│
├── Both transient and sustained
│   └── Retry with Backoff → Circuit Breaker (escalation)
│       Retry first → if retries exhausted → trip circuit
│
└── Cascading failure risk
    └── Circuit Breaker + Bulkhead + Timeout
        Isolate failing service → fail fast → protect callers
```

---

## 6. Migration Strategy Selection

```
Migrating from monolith?
│
├── Application size?
│   ├── Small (< 5 bounded contexts) → Direct decomposition
│   └── Large (5+ bounded contexts) → Strangler Fig (incremental)
│
├── Risk tolerance?
│   ├── Low (production critical) → Strangler Fig + ACL
│   ├── Medium → Strangler Fig (faster pace)
│   └── High (can tolerate downtime) → Big-bang rewrite (not recommended)
│
├── Domain boundaries clear?
│   ├── Yes → Start extracting services
│   └── No → Event storming + DDD first, then Strangler Fig
│
├── Shared database?
│   ├── Yes → Plan database decomposition with Transactional Outbox
│   └── No → Easier migration path
│
└── Inter-service communication in monolith?
    ├── Tight coupling → ACL mandatory before extraction
    └── Loose coupling → Direct extraction possible
```

---

## 7. Consulting Engagement Decision Framework

Use this to guide initial client conversations:

### Assessment Questions

| # | Question | Maps to Pattern |
|---|---------|----------------|
| 1 | Are you migrating from a monolith? | Strangler Fig, ACL |
| 2 | Do you need transactions across services? | Saga (Orch/Choreo) |
| 3 | Do services fail and cascade? | Circuit Breaker, Retry |
| 4 | Do you need async event communication? | Pub-Sub, Event Sourcing |
| 5 | Do you need audit trail / compliance? | Event Sourcing |
| 6 | Are DB updates + events inconsistent? | Transactional Outbox |
| 7 | Do you need parallel data aggregation? | Scatter-Gather |
| 8 | Are you concerned about testability? | Hexagonal Architecture |
| 9 | How do you expose APIs to consumers? | API Routing (Hostname/Path/Header) |
| 10 | What is your team structure? | Influences all pattern choices |

### Maturity-Based Recommendations

| Client Maturity | Start With | Then Add |
|----------------|-----------|---------|
| **Monolith, just starting** | Strangler Fig + Path Routing | ACL + Circuit Breaker |
| **Some microservices, inconsistent** | Pub-Sub + Transactional Outbox | Saga + Event Sourcing |
| **Microservices, reliability issues** | Circuit Breaker + Retry | Scatter-Gather + Saga |
| **Greenfield microservices** | Hexagonal Architecture + Pub-Sub | Event Sourcing + Saga |

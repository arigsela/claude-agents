# Capacity Estimation

Back-of-envelope numbers decide the design: they say whether one database is enough,
whether the cache matters, and what breaks first. Aim for the right order of magnitude,
not precision. Write every assumption down, round hard, and show the arithmetic so the
client can change one input and redo it.

## Method

1. Write the assumptions: users, actions per user per day, payload and record sizes,
   read:write ratio, retention, growth.
2. Compute the average rate for reads and writes separately.
3. Apply a peak factor. Size for the peak, not the average.
4. Derive storage, bandwidth, cache and instance counts from the rates.
5. Compare each number with what one node can do (below) and say what it implies.

## Time and size conversions

| Quantity | Value | Shortcut |
|---|---|---|
| Seconds per day | 86,400 | ≈ 10⁵ |
| Seconds per month | ≈ 2.6 million | |
| Seconds per year | ≈ 31.5 million | ≈ π × 10⁷ |
| 1 million per day | ≈ 12 per second | |
| 1 billion per day | ≈ 11,600 per second | |
| 2¹⁰ / 2²⁰ / 2³⁰ / 2⁴⁰ / 2⁵⁰ bytes | KB / MB / GB / TB / PB | each step ≈ ×1,000 |

Typical sizes: an integer or timestamp 8 bytes; a UUID 16 bytes binary, 36 as text; a
short text row with metadata 0.2–1 KB; a JSON API response 1–20 KB; a phone photo
0.2–3 MB. Video size is bitrate × duration: 5 Mbit/s for 60 s ≈ 37.5 MB.

## Formulas

| What | Formula | Notes |
|---|---|---|
| Average rate | DAU × actions per user per day ÷ 86,400 | Do reads and writes separately |
| Peak rate | average × peak factor | 2–3× for a daily consumer cycle; 10× or more for launches, flash sales, campaigns. Use measured peaks when they exist |
| Storage per year | writes per day × bytes per record × 365 × replication × overhead | Replication is often 3×; indexes and fragmentation add 1.2–2× |
| Bandwidth | rate × average payload | Ingress and egress separately; egress is what costs money |
| Cache size | hot fraction × daily read working set | Start with 20% of a day's distinct reads (the 80/20 heuristic), then measure the hit ratio |
| Instances | peak rate ÷ sustainable rate per instance ÷ target utilization | Target 60–70% utilization at peak, and still fit the peak after losing one zone |
| Concurrency (Little's law) | in-flight requests = arrival rate × time in system | 2,000 req/s × 50 ms = 100 in flight; sizes connection pools, threads, open sockets |

## What one node can do (order of magnitude)

Measure the real system with a load test before committing; these numbers only say
whether a design is in the right range.

| Component | Rough ceiling per node | Watch out |
|---|---|---|
| Stateless web/app instance | 1,000–10,000 simple req/s | Depends entirely on the work per request |
| Relational primary (PostgreSQL/MySQL) | ~10,000 simple writes/s; more for reads | Hot rows, lock contention and large transactions cut this sharply |
| Redis / Valkey / Memcached | ~100,000 simple ops/s | Command execution is single-threaded in Redis; a Lua script costs several commands; big keys and slow commands block |
| Kafka partition | ~10 MB/s | Throughput scales with partitions; ordering holds only within one |
| One WebSocket gateway | 10,000s to ~1 million idle connections | Memory per connection and fan-out bursts, not CPU, set the limit |

## Latency reference numbers

| Operation | Approximate latency |
|---|---|
| Main memory reference | ~100 ns |
| SSD random read (4 KB) | ~20–100 µs |
| Read 1 MB sequentially from SSD | ~0.5–1 ms |
| Round trip within one data center or zone | ~0.5 ms |
| Round trip between zones in one region | ~1–2 ms |
| Cache GET over the network (Redis) | ~0.2–1 ms |
| Indexed primary-key database read, network included | ~1–5 ms |
| HDD seek | ~10 ms |
| Round trip US East ↔ US West | ~60–70 ms |
| Round trip US ↔ Europe | ~80–150 ms |
| New TCP + TLS connection, before the first request | +2 round trips (TLS 1.3) or +3 (TLS 1.2) |

What follows from them: memory beats SSD beats the network; a request that makes ten
sequential cross-region calls cannot meet a 200 ms target; and connection reuse matters
for far-away users because every new TLS connection costs round trips.

## Availability and downtime

| Availability | Downtime per year | Per 30-day month |
|---|---|---|
| 99% | 3.65 days | 7.2 hours |
| 99.5% | 1.83 days | 3.6 hours |
| 99.9% | 8.76 hours | 43.2 minutes |
| 99.95% | 4.38 hours | 21.6 minutes |
| 99.99% | 52.6 minutes | 4.3 minutes |
| 99.999% | 5.3 minutes | 26 seconds |

Composite availability:

- **Dependencies in series multiply.** Three required dependencies at 99.9% each give at
  most 99.9³ ≈ 99.7%. A target can't be higher than the product of what it hard-depends on.
- **Redundant copies combine as 1 − (1 − A)ⁿ.** Two independent 99% copies give 99.99%,
  but only if they fail independently. Copies sharing a zone, a deploy or a config don't.
- Each extra nine costs roughly an order of magnitude more effort. Ask what the business
  loses per hour of downtime before promising one.

## Worked example: a comments service

Assumptions: 20 million DAU; each user loads 10 comment pages a day (about 20 comments,
~10 KB per page) and writes 2 comments of ~500 bytes; the day's 200 million page reads
touch about 5 million distinct pages, mostly recent and popular threads; peak factor 3;
replication 3×; index overhead 1.5×.

| Quantity | Arithmetic | Result |
|---|---|---|
| Page reads | 20M × 10 ÷ 86,400 ≈ 2,300/s average, × 3 | ~7,000/s peak |
| Comment writes | 20M × 2 ÷ 86,400 ≈ 460/s average, × 3 | ~1,400/s peak |
| Read:write ratio | 200M : 40M per day | 5:1 by requests |
| Egress at peak | 7,000/s × 10 KB = 70 MB/s | ~560 Mbit/s |
| Raw data | 40M × 500 B = 20 GB/day × 365 | ~7.3 TB/year |
| Per copy (each node holds one) | 7.3 TB × 1.5 index overhead | ~11 TB/year |
| Total stored, all copies | 11 TB × 3 replicas | ~33 TB/year (drives storage cost) |
| Read working set | 5M distinct pages × 10 KB | ~50 GB/day |
| Cache for the hot 20% | 20% × 50 GB | ~10 GB, one cache node (or a replicated pair) |

What the numbers say: writes fit on one relational primary with room to spare; reads
fit on replicas plus a small cache. Storage growth is the number to watch: each copy
grows by about 11 TB a year, which large managed instances can hold for a few years,
but backups, restores, index rebuilds and new replicas get slower as it grows. Plan to
partition by thread ID or move comments older than a few months to cheaper storage
before the restore time breaks the recovery target. Nothing here needs sharding at
launch.

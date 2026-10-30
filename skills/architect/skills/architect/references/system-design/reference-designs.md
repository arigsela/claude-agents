# Reference Designs

Short worked designs for problems that come up again and again. Each gives the hard
part, the decisions that settle it, and what breaks first. Use them as a starting point:
re-run the estimate with the client's numbers and change what their requirements change.
The moves they share are collected at the end.

---

## URL shortener

**Hard part:** generating short, unique codes, and serving a very read-heavy redirect
path fast.

- **Codes:** base62 over 7 characters gives 62⁷ ≈ 3.5 trillion codes. Hashing the URL and
  truncating collides and needs a check-and-retry; a counter or range allocation (each
  server takes a block of IDs) never collides. Range allocation is the usual choice; add
  a random component if codes must not be guessable.
- **Store:** key-value, keyed by code, plus a cache for hot links (a small fraction of
  links gets most clicks).
- **Redirect status:** 301 lets browsers cache the redirect, which loses click counts;
  302 keeps every click visible. Use 302 when analytics matter.
- **Analytics:** write click events to a stream, not to the link record.
- **Breaks first:** the single counter (fix with ranges), viral links (cache), abuse
  (rate-limit creation, scan targets for malware).

## Chat and messaging

**Hard part:** real-time delivery over long-lived connections, without losing or
reordering messages.

- **Connections:** clients hold WebSockets to a gateway tier. A registry (Redis, with a
  TTL refreshed by heartbeat) maps user → gateway so any service can route a message.
- **Write path:** persist first, then deliver. Store messages in a wide-column or
  partitioned store keyed by conversation ID and a per-conversation sequence number;
  "load the last N messages" is one partition read.
- **Delivery:** ack from the recipient's device; retry until acked (at-least-once);
  clients dedupe by message ID. Offline users get store-and-forward plus a mobile push.
- **Order:** a per-conversation sequence assigned by one writer per conversation, not
  timestamps from many machines.
- **Presence:** heartbeats with TTL expiry; publish presence only to a user's contacts or
  open conversations, never to everyone.
- **Groups:** fan out per member through a queue; very large groups (channels) switch to
  pull.
- **Breaks first:** gateway memory and reconnect storms after a gateway restart (spread
  reconnects with jitter), large-group fan-out, hot conversations.

## News feed / timeline

**Hard part:** building each user's feed fast when some authors have millions of
followers.

- **Fan-out on write (push):** at post time, append the post ID to every follower's
  precomputed feed (a capped list per user in Redis). Reads are one lookup; writes cost
  one insert per follower.
- **Fan-out on read (pull):** at read time, fetch recent posts from everyone the user
  follows and merge. Writes are cheap; reads are expensive.
- **Hybrid (the usual answer):** push for normal authors; pull for authors above a
  follower threshold and merge their posts in at read time.
- Store post IDs in feeds, not post bodies; hydrate from a post cache.
- **Ranking:** chronological is cheap; ranked feeds add a candidate-generation and
  scoring stage.
- **Breaks first:** write amplification from big accounts, feed cache memory for
  inactive users (only precompute for active users), and p99 feed-read latency.

## Video streaming

**Hard part:** storing and delivering huge files worldwide without buffering.

- **Upload:** clients upload directly to object storage (pre-signed or multipart URLs),
  not through the app tier.
- **Transcoding:** split into chunks and encode them in parallel into a bitrate ladder
  (240p … 4K) through a queue and an autoscaled worker fleet. The work is async; the video
  becomes playable when the first renditions finish.
- **Playback:** adaptive bitrate (HLS or DASH): the player reads a manifest and switches
  quality per segment as bandwidth changes.
- **Delivery:** a CDN in front of object storage; pre-position popular titles at the
  edge. Never serve video bytes from the application or a database.
- **Metadata:** in a database; view counts as batched or approximate counters.
- **Breaks first:** egress cost and origin load (CDN hit ratio is the key metric), the
  transcoding backlog after upload spikes.

## Ride matching and other geo search

**Hard part:** finding nearby drivers among millions of moving points, updated every few
seconds.

- **Geo index:** divide the map into cells (geohash, S2 or H3, or a quadtree). Search the
  rider's cell and its neighbours, then rank by distance or ETA. Geohashes of nearby
  points share prefixes, so proximity becomes a prefix or range lookup.
- **Location writes:** millions of pings a minute don't belong in the transactional
  database. Keep live positions in memory (Redis GEO or an in-memory cell index), stream
  pings through Kafka, and persist history in batches.
- **Trips:** a state machine in a relational database (requested → matched → en route →
  completed / cancelled), with strong consistency so a driver can't be matched twice
  (conditional update on driver status).
- **Breaks first:** dense city cells (use smaller cells there), the location write rate,
  and double-matching under concurrency.

## Marketplace ordering (food delivery)

**Hard part:** an order lifecycle across three parties, under sharp meal-time peaks.

- **Order:** an explicit state machine (placed → accepted → preparing → picked up →
  delivered, plus cancel and refund paths) in a relational database; each transition
  publishes an event that drives tracking, notifications and payouts.
- **Discovery:** restaurants and menus in a search index with geo filters, cached
  heavily; the database stays the source of truth.
- **Dispatch:** the geo matching above, plus ETA from prep time and travel time.
- **Peaks:** queues in front of non-urgent work, autoscaling ahead of known meal times
  (scheduled scaling), and load shedding of non-essential features.
- **Breaks first:** dispatch at peak, and state drift between services (make every
  transition idempotent and keyed by order ID and target state).

## E-commerce checkout and inventory

**Hard part:** never overselling and never double-charging, while browsing stays fast
and cheap.

- **Split by consistency:** catalog, search, reviews and recommendations are read-heavy
  and eventually consistent (cache and search index). Inventory, orders and payments are
  strongly consistent in a relational database.
- **Overselling:** an atomic conditional decrement, or a reservation with expiry during
  checkout (see `building-blocks.md` §4).
- **Checkout across services:** a saga (reserve stock → authorize payment → create
  order → confirm), with compensations (release stock, void authorization), driven by
  the outbox pattern. Idempotency keys on every payment call.
- **Flash sales:** a waiting room or queue at the entrance, per-user purchase limits,
  rate limits at the edge, and pre-split inventory for the hot item.
- **Breaks first:** the hot item's inventory row, the payment provider's limits, and
  cache stampedes on the sale page at the start time.

## File storage and sync

**Hard part:** syncing large files across devices efficiently and never losing data.

- **Chunking:** split files into blocks (fixed size such as 4 MB, or content-defined
  chunks so an insert doesn't shift every block). Store chunks in object storage keyed by
  their content hash, so identical chunks are stored once (deduplication).
- **Delta sync:** on change, upload only chunks whose hashes are new; a file version is
  an ordered list of chunk hashes in a metadata database.
- **Notify:** other devices learn of changes by long-poll or a push channel, then pull
  the chunks they lack.
- **Conflicts:** concurrent edits create a conflicted copy or a merge; don't silently
  apply last-writer-wins to user files.
- **Breaks first:** the metadata service (partition by user or namespace), the
  notification fan-out for shared folders, and garbage collection of unreferenced chunks.

## Notification service

**Hard part:** delivering through unreliable third-party providers, at bursty volume,
without duplicates and without letting bulk traffic delay urgent messages.

- **Flow:** producers → notification API (validate, authorize, attach an idempotency key,
  check preferences) → durable queue or log → per-channel workers → provider adapters
  (APNs/FCM, email, SMS) → status store fed by provider receipts and webhooks.
- **Priority lanes:** separate queues and worker pools for transactional messages (OTP,
  password reset, security alerts) and bulk messages (campaigns), so a campaign can never
  delay a login code.
- **No duplicates:** a key per (event, recipient, channel) recorded before sending;
  pass the key to providers that accept one. A timeout after a successful send is the
  classic duplicate source: the outcome is unknown, so no queue can make it exactly-once.
  Decide per message type: retry OTPs (a duplicate beats no code), retry transactional
  messages once, don't retry marketing. Set the push collapse ID (`apns-collapse-id`,
  the Android notification `tag`) to the message ID so a repeat replaces the first on
  the device.
- **Expiry per type:** an OTP older than about a minute is useless (the user already
  pressed resend); campaign messages expire with the campaign. Drop expired messages
  instead of sending a backlog late after an outage.
- **Provider failures:** per-provider rate limiting (a shared token bucket set below the
  contracted quota, with a reserved share for urgent lanes), circuit breakers, and a
  fallback provider for SMS and email kept warm with a share of live traffic; on
  failover, resend the same OTP. Push has no alternative provider: queue until expiry,
  and fall back to another channel only for critical messages.
- **Campaigns:** a job that releases recipients at a controlled rate with saved progress
  and a stop button, instead of enqueueing every recipient at once; respect time zones
  and quiet hours. Provider quotas, not your servers, usually set the send rate, and the
  wave of app opens afterwards hits your own backends.
- **Preferences and compliance:** opt-outs, quiet hours, frequency caps and unsubscribe
  checked at send time in one place; bounces, complaints and dead push tokens (APNs 410,
  FCM `UNREGISTERED`) feed a suppression list.
- **Abuse:** OTP endpoints attract SMS pumping fraud; rate-limit per phone number, IP and
  device, allow-list countries, and alert when the share of codes actually used drops.
  Keep OTP values out of logs and status records.
- **Cost:** provider fees, SMS above all, dwarf the infrastructure; prefer push, cap
  messages per user, and show each sending team its spend.
- **Breaks first:** provider quotas during a campaign, duplicate sends on retry, and the
  status store's write volume (several status updates per message).

## Rate limiter

**Hard part:** a shared, consistent count on every request, adding about a millisecond.

- Token bucket per API key in Redis via an atomic script; limits configured per plan.
- Middleware or the API gateway does the check; reject with 429 and `Retry-After`.
- Decide fail-open or fail-closed per route; keep a local per-instance backstop.
- Details, algorithm choice and failure policy: `building-blocks.md` §7.

## Leaderboard

**Hard part:** ranks over millions of players, updated constantly, read in real time.

- A sorted set per board (Redis `ZADD`, `ZRANGE … REV`, `ZREVRANK`) gives O(log n)
  updates and rank lookups. Persist scores in a database as the source of truth.
- Time-boxed boards (daily, weekly) as separate keys with expiry.
- Very large boards: shard by score range or by region and merge the top N; show exact
  ranks near the top and approximate percentiles elsewhere.

## Search autocomplete

**Hard part:** returning the top suggestions within a few tens of milliseconds as the
user types.

- Precompute the top-k completions per prefix offline from query logs (a trie or a
  prefix → list table), rebuilt periodically; serve from memory or cache.
- Cache popular prefixes at the edge; debounce on the client; filter blocked terms.
- Personalization or freshness as a small online layer merged on top.

## Web crawler

**Hard part:** crawling billions of pages politely, without fetching the same thing
twice.

- A URL frontier of per-host queues: politeness delays, `robots.txt`, and priority by
  importance and change rate.
- Deduplicate URLs (normalize, then a hash set or a Bloom filter) and content (hash of
  the page body).
- Fetchers are stateless workers; DNS caching matters; store raw pages in object storage
  and hand them to parsing and indexing through a queue.
- Watch for crawler traps (infinite calendars, session IDs in URLs): cap depth and pages
  per host.

## Payments

**Hard part:** never losing or duplicating money across your system and external
processors.

- A double-entry ledger (every movement is balanced debits and credits) in a relational
  database; balances are derived, never edited in place.
- A payment state machine with idempotency keys on every external call; treat timeouts
  as unknown and resolve them by querying the processor.
- Daily reconciliation against processor and bank reports; alert on any mismatch.
- Strong consistency and an append-only audit trail; never cache balances for decisions.

---

## Moves that recur

| Move | Used in | Use when |
|---|---|---|
| Key-value store plus cache | URL shortener, feed hydration, sessions | Reads are lookups by key and greatly outnumber writes |
| Range-allocated or time-ordered IDs | URL shortener, chat, posts | Many writers need unique IDs without a per-ID round trip |
| Fan-out on write, pull for big senders | News feed, group chat | Readers outnumber writers but a few writers have huge audiences |
| Persist, then deliver with ack and retry | Chat, notifications, webhooks | Messages must not be lost; consumers dedupe |
| Geo cells plus an in-memory live index | Ride matching, delivery dispatch | "Near me" queries over moving points |
| State machine plus an event per transition | Trips, orders, payments | A lifecycle spans services and must be auditable |
| Queue plus autoscaled workers | Transcoding, notifications, crawling | Slow or bursty work that can finish later |
| CDN plus object storage | Video, images, downloads | Large or static content served worldwide |
| Content-addressed chunks | File sync, backups | Large files with small edits; dedup across users |
| Separate lanes per priority | Notifications, job systems | Bulk work must not delay urgent work |
| Consistency chosen per component | E-commerce, marketplaces | Most data can lag, but money and stock can't |
| Saga plus idempotency keys | Checkout, payments, bookings | One business action spans services or external providers |
| Approximate or batched counters | Views, likes, analytics | Exact counts aren't worth the write contention |
| Sharding by user or tenant with consistent hashing | Metadata services, chat, feeds | One node can't hold the data or the write rate |

# 12-Factor App -- Deep Dive Reference

Source: [12factor.net](https://12factor.net/) by Adam Wiggins

This reference provides detailed guidance for each factor, including what compliance looks like, common violations, and remediation patterns.

---

## I. Codebase -- One codebase tracked in revision control, many deploys

**Compliant when:**
- Single repo per application (1:1 codebase-to-app)
- Same codebase deploys to dev, staging, production
- Shared code is extracted into libraries, not duplicated

**Common violations:**
- Multiple apps sharing a single repo without clear boundaries (monorepo without tooling)
- Copy-pasting code between repos instead of creating shared libraries
- Different code branches for different environments

**Remediation:**
- Adopt a 1:1 repo-to-deployable-unit model
- Use package managers for shared libraries
- Use environment-specific config (Factor III), not environment-specific code

---

## II. Dependencies -- Explicitly declare and isolate

**Compliant when:**
- All dependencies declared in a manifest (package.json, requirements.txt, go.mod, Gemfile, pom.xml)
- Dependency isolation tool used (virtualenv, bundler, Docker, nix)
- No reliance on system-wide packages or tools

**Common violations:**
- "Works on my machine" because of implicit system dependencies
- Shell-outs to system tools (curl, imagemagick) without declaring them
- Missing lock files (package-lock.json, Pipfile.lock, yarn.lock)

**Remediation:**
- Add lock files to version control
- Containerize to isolate from host system
- Vendor or declare all system-level dependencies

---

## III. Config -- Store config in the environment

**Compliant when:**
- All deployment-varying config lives in environment variables
- No credentials, URLs, or feature flags hardcoded in source
- Codebase could be open-sourced without exposing secrets

**Common violations:**
- Config files checked into Git (database.yml, .env files with real secrets)
- Constants file with production URLs
- Build-time config baked into artifacts

**Remediation:**
- Use env vars for all deployment-specific values
- Use a secrets manager (Vault, AWS Secrets Manager, GCP Secret Manager) for sensitive values
- Validate that no secrets exist in the repo (use tools like git-secrets, trufflehog)

---

## IV. Backing Services -- Treat as attached resources

**Compliant when:**
- Databases, caches, queues, email services, etc. are consumed via config (URLs/credentials in env vars)
- Swapping a local Postgres for a managed RDS requires zero code changes
- No distinction between local and third-party services in code

**Common violations:**
- Hardcoded connection strings
- Direct filesystem access instead of object storage
- Tightly coupled to a specific vendor's SDK without abstraction

**Remediation:**
- Abstract service access behind interfaces/adapters
- Use connection strings from env vars
- Test with both local and managed services

---

## V. Build, Release, Run -- Strictly separate stages

**Compliant when:**
- Build produces a versioned artifact (Docker image, compiled binary, bundled package)
- Release = artifact + environment config (immutable, uniquely identified)
- Run stage simply starts the release; no code changes possible at runtime

**Common violations:**
- SSH into production to hotfix code
- Build artifacts that contain environment-specific config
- No release versioning or tagging

**Remediation:**
- Implement CI/CD pipeline with distinct build/release/run stages
- Tag every release with a unique identifier (git SHA, semantic version, timestamp)
- Make releases immutable -- rollback by deploying a previous release, not patching

---

## VI. Processes -- Stateless and share-nothing

**Compliant when:**
- Application processes store nothing locally between requests
- All persistent data lives in backing services (databases, caches, object stores)
- Any process can be killed and replaced without data loss

**Common violations:**
- Storing uploads or session data on local disk
- In-memory caches that aren't backed by an external store
- Sticky sessions (session affinity) in load balancers

**Remediation:**
- Move session state to Redis/Memcached or a database
- Use object storage (S3, GCS) for file uploads
- Design processes to be interchangeable and replaceable

---

## VII. Port Binding -- Export services via port binding

**Compliant when:**
- App includes its own HTTP server (e.g., embedded Jetty, Puma, Gunicorn, Express)
- App binds to a port and listens for requests
- No dependency on an external application server container

**Common violations:**
- Deploying a WAR file into Tomcat
- Requiring Apache/Nginx as a hard dependency (as opposed to a reverse proxy in front)

**Remediation:**
- Embed the web server in the app
- Bind to a port specified by an env var (e.g., PORT)
- Use a reverse proxy (Nginx, ALB, Envoy) in front for TLS termination and routing

---

## VIII. Concurrency -- Scale out via the process model

**Compliant when:**
- Different workloads run as different process types (web, worker, scheduler)
- Scaling is horizontal (add more processes) not vertical (bigger machine)
- Process lifecycle managed by the platform (systemd, container orchestrator)

**Common violations:**
- Single monolithic process handling web, background jobs, and cron
- Scaling by increasing RAM/CPU on a single instance
- App managing its own daemon/thread pool lifecycle

**Remediation:**
- Separate concerns into distinct process types (Procfile, Docker Compose services)
- Use a process manager or orchestrator (Kubernetes, ECS, Nomad)
- Design each process type to scale independently

---

## IX. Disposability -- Fast startup, graceful shutdown

**Compliant when:**
- Process starts in seconds (not minutes)
- SIGTERM triggers graceful shutdown (drain connections, finish current work)
- Workers return jobs to queue on shutdown; jobs are idempotent and crash-safe

**Common violations:**
- Multi-minute startup due to cache warming or large initializations
- Abrupt shutdown that drops in-flight requests
- Background jobs that can't be safely interrupted and retried

**Remediation:**
- Lazy-load expensive resources
- Implement graceful shutdown handlers
- Design jobs to be idempotent (safe to retry)
- Use robust queuing with visibility timeouts

---

## X. Dev/Prod Parity -- Keep environments identical

**Compliant when:**
- Same backing services in dev and production (same database engine, same cache, same queue)
- Deploys happen within hours of code being written
- Developers who write code also deploy and observe it in production

**Common violations:**
- SQLite in dev, PostgreSQL in prod
- Using mock services or in-memory fakes in development
- Weeks-long staging cycles before production deployment

**Remediation:**
- Use Docker Compose or similar to run production-identical services locally
- Deploy to production frequently (daily or more)
- Close the feedback loop -- developers observe production behavior

---

## XI. Logs -- Treat as event streams

**Compliant when:**
- App writes to stdout/stderr, not to log files
- Log routing, aggregation, and storage handled by the platform
- Structured logging (JSON) for machine parseability

**Common violations:**
- Writing to /var/log/app.log inside the container
- App-level log rotation configuration
- Unstructured log formats that resist parsing

**Remediation:**
- Configure logging frameworks to output to stdout
- Use a log aggregator (ELK, Datadog, CloudWatch Logs, Loki)
- Adopt structured logging with consistent fields (timestamp, level, service, trace_id)

---

## XII. Admin Processes -- Run as one-off processes

**Compliant when:**
- Database migrations, data fixes, and console sessions run with the same codebase, config, and deps as the app
- Admin scripts ship with the app code (not separate repos or ad-hoc scripts)
- One-off processes run in the same environment as long-running processes

**Common violations:**
- Running migrations from a developer laptop against production
- Admin scripts with their own dependency sets
- Manual SQL queries run directly against production databases

**Remediation:**
- Include migration and admin tooling in the app codebase
- Run admin processes via the same deployment mechanism (e.g., `kubectl exec`, ECS run-task)
- Automate migrations as part of the release pipeline

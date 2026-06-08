# Vela Codebase Security & Quality Scan Report
Date: 2026-06-06

## Executive Summary

The Vela VPP (Virtual Power Plant) platform is a large Python/FastAPI codebase spanning 40+ modules covering market dispatch, battery optimization, ISO market integrations, ML forecasting, and SCADA/ICS protocols. The codebase exhibits a strong architectural foundation with good use of Pydantic validation, async patterns, and structured logging. However, several critical and high-severity issues were identified: the entire REST API and GraphQL layer operates without any authentication enforcement on routes (auth infrastructure exists but is not wired to routers), a hardcoded insecure JWT fallback secret is loaded at module import time, CORS is fully open, and the vast majority of API endpoints return purely synthetic random data rather than real values — a significant data-integrity risk if deployed to production users. Application-layer rate limiting is implemented twice but wired in nowhere, leaving expensive endpoints (notably the event-loop-blocking MILP dispatch solve) protected only by coarse IP-based limits at the edge — and unprotected entirely on any path that bypasses the proxy. A total of 44 distinct issues were found.

---

## Issue Counts by Severity

| Severity | Count |
|----------|-------|
| Critical |   4   |
| High     |  13   |
| Medium   |  16   |
| Low      |  11   |

---

## Issues

---

### [CRITICAL-1] JWT secret has an insecure hardcoded default that is loaded at import time

- **File**: `vela/api/auth.py:16`
- **Category**: Security — Hardcoded Secret
- **Problem**: `JWT_SECRET = os.getenv("JWT_SECRET", "changeme-insecure")`. This module-level variable is resolved at import. If `JWT_SECRET` is absent from the environment, every JWT issued will be signed with the string `"changeme-insecure"`, which any attacker can use to forge arbitrary tokens with any role claim.
- **Fix**: Remove the default value entirely: `JWT_SECRET = os.getenv("JWT_SECRET")`. Add a startup guard that raises `RuntimeError` if the value is `None` or equal to a known weak value. The same fallback exists in `vela/security/secrets.py:90` (`"insecure-dev-secret"`) and should be removed.

---

### [CRITICAL-2] All REST API routes and the GraphQL layer have no authentication or authorization enforced

- **File**: `vela/api/app.py:31-35`, all router files under `vela/api/routers/`
- **Category**: Security — Missing Auth Check
- **Problem**: The `create_app()` factory registers all routers (assets, dispatch, forecasts, market, settlements) without any authentication middleware or per-route `Depends(get_current_user)`. The auth infrastructure in `vela/api/dependencies.py` exists and works, but no router uses `CurrentUser`, `require_role()`, or `require_permission()` as a dependency. A grep for `CurrentUser` or `require_role` in `vela/api/routers/` returns zero results. Any unauthenticated caller can read dispatch plans, create bids, finalize settlement statements, modify system config, and manage users.
- **Fix**: Add `dependencies=[Depends(get_current_user)]` (or role-specific factories) to each `app.include_router(...)` call, or add the dependency to individual route functions. Admin endpoints (user create/deactivate, config write) need `require_role("admin")`.

---

### [CRITICAL-3] CORS policy allows all origins, all methods, and all headers

- **File**: `vela/api/app.py:25-30`
- **Category**: Security — Insecure Configuration
- **Problem**: `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`. This enables cross-site request forgery from any web page on the internet against any user who has a valid session token stored in the browser.
- **Fix**: Restrict `allow_origins` to the known dashboard and application origins (e.g., `["https://app.vela.energy"]` in production). Use the `CORS_ALLOWED_ORIGINS` env variable already defined in `.env.example`. Never use wildcard in combination with `allow_credentials=True`.

---

### [CRITICAL-4] SSL/TLS certificate verification is disabled for IEEE 2030.5 client

- **File**: `vela/m2_protocols/ieee2030_5.py:134`
- **Category**: Security — Insecure Crypto / MITM
- **Problem**: `verify=False` is passed to `httpx.AsyncClient`. This comment says "In production, use proper CA verification" but the code ships disabled. IEEE 2030.5 is the protocol used for DER (Distributed Energy Resource) command and control. An attacker on the network path can impersonate the utility server and send fraudulent dispatch commands to grid-connected assets.
- **Fix**: Remove `verify=False`. Implement the commented mutual TLS setup using the `cert_path` and `key_path` parameters that are already in the constructor signature. Use a proper CA bundle or pinned certificate.

---

### [HIGH-1] GraphiQL IDE is exposed unconditionally (no environment guard)

- **File**: `vela/graphql/schema.py:17`
- **Category**: Security — Exposed Sensitive Interface
- **Problem**: `GraphQLRouter(schema, graphiql=True)`. GraphiQL provides a full IDE for introspecting the schema, building queries, and running mutations — and this router is served without authentication (see CRITICAL-2). In production this gives attackers a point-and-click interface for exploring and attacking the API.
- **Fix**: Disable in production: `graphiql=os.getenv("VELA_ENV") != "production"`.

---

### [HIGH-2] API key hashes list is never populated — API key auth is permanently broken

- **File**: `vela/api/dependencies.py:52`
- **Category**: Security / Bug — Missing Initialization
- **Problem**: `KNOWN_API_KEY_HASHES: list[str] = []`. This module-level list is used by `authenticate_request()` for API-key validation. There is no code anywhere in the codebase that populates it at startup. As a result, every API key authentication attempt fails with `AuthenticationError("Invalid API key")`, and the only working auth path is JWT. If an operator issues an API key it will never work.
- **Fix**: Add startup logic (lifespan handler or a startup event) that loads hashed API keys from the database or secrets manager into this list.

---

### [HIGH-3] Inbound webhook endpoint skips HMAC signature verification

- **File**: `vela/api/routers/webhooks.py:133-145`
- **Category**: Security — Missing Auth Check / Injection
- **Problem**: The `receive_inbound/{source}` endpoint reads the request body and returns a success response. The comment says "In production: look up signing secret by source and verify" but no verification is implemented. An attacker can POST arbitrary payloads pretending to be any ISO, utility, or partner system.
- **Fix**: Implement the HMAC-SHA256 signature check using the `X-Webhook-Signature` header, keyed to a per-source secret stored in the secrets manager.

---

### [HIGH-4] Dispatch optimization runs in a sync background task inside an async worker — blocks the event loop

- **File**: `vela/api/routers/dispatch.py:66-97`
- **Category**: Bug / Performance — Blocking Call in Async Context
- **Problem**: `background_tasks.add_task(_run_optimization, plan_id, request)` calls a regular synchronous function `_run_optimization` which performs CPU-intensive MILP solving (potentially many seconds). `BackgroundTasks` in FastAPI runs these functions in the same event loop thread. A long-running MILP solve will block all other requests.
- **Fix**: Move the solve to a Celery worker (already available via `vela/workers/optimization_worker.py`) or use `asyncio.to_thread()` to run the sync solve in a thread pool executor.

---

### [HIGH-5] `hash_api_key` uses plain SHA-256 without a salt — vulnerable to rainbow table attacks

- **File**: `vela/api/auth.py:42-44`
- **Category**: Security — Insecure Crypto
- **Problem**: `hashlib.sha256(raw_key.encode()).hexdigest()` stores API key hashes without any salt. SHA-256 without a salt is fast and precomputable. An attacker who obtains the hash table can recover common or short keys via brute force.
- **Fix**: Use `hashlib.scrypt` or `bcrypt` for API key hashing, or at minimum include a per-key random salt stored alongside the hash. The `.env.example` mentions `API_KEY_SALT` but it is not used in the hashing implementation.

---

### [HIGH-6] Admin endpoints (user management, config writes) have no role or auth enforcement

- **File**: `vela/api/routers/admin.py:66-152`
- **Category**: Security — Missing Auth Check
- **Problem**: The admin router defines `POST /users`, `PATCH /users/{id}/deactivate`, `PUT /config/{key}`, `GET /audit` — all without any authentication dependency. This is a subset of CRITICAL-2 but the admin surface is particularly sensitive: any caller can create a new admin user, change system configuration, or read the audit trail.
- **Fix**: This router should require `require_role("admin")` on every endpoint, in addition to the global auth fix.

---

### [HIGH-7] Module-level in-memory stores grow without bound — memory leak in production

- **File**: `vela/api/routers/dispatch.py:43`, `vela/api/routers/telemetry.py:44`, `vela/api/routers/settlements.py:47`, `vela/api/routers/market.py:50`, `vela/api/routers/bids.py:45`, `vela/api/routers/webhooks.py:57`, `vela/api/routers/admin.py:63`
- **Category**: Bug — Resource Leak / Memory
- **Problem**: All core resources (dispatch plans, telemetry points, settlement statements, market bids, webhook deliveries, audit entries) are stored in module-level `dict` or `list` variables. These are never evicted, bounded, or persisted. A long-running API process will leak memory indefinitely, and data is lost on restart. `_STORE: list[TelemetryPoint] = []` can accept 10,000 points per batch with no limit.
- **Fix**: Replace with database-backed persistence using the already-defined ORM models in `vela/m4_state/database.py`. For short-term caching, apply size limits and TTL eviction.

---

### [HIGH-8] `SettlementEngine.calculate()` uses `assert` for data validation — silently broken with Python `-O` flag

- **File**: `vela/m9_settlement/settlement_engine.py:113`
- **Category**: Bug — Unreliable Validation
- **Problem**: `assert len(_scheduled) == len(_metered) == len(_lmp) == len(timestamps)`. Python `assert` statements are stripped at runtime when the interpreter is invoked with the `-O` (optimize) flag, which many production deployments use. A length mismatch will silently produce wrong settlement calculations — an incorrect financial outcome.
- **Fix**: Replace with an explicit `if` check and `raise ValueError(...)`.

---

### [HIGH-9] `ARPriceModel.predict()` uses `assert self._fitted` — crashes in production instead of raising a domain error

- **File**: `vela/m5_forecasting/price_forecast.py:37`
- **Category**: Bug — Unreliable Validation
- **Problem**: Same issue as HIGH-8. The `assert` is also silenced by `-O`. Additionally, if the assert fires, it produces `AssertionError` which is not caught by the calling code in `vela/orchestrator/loop.py:144`, causing the forecast phase to fail.
- **Fix**: Use `if not self._fitted: raise RuntimeError("Model must be fitted before prediction")`.

---

### [HIGH-10] `ModbusTCPClient._send_recv()` uses bare `assert` for connection state check

- **File**: `vela/m2_protocols/modbus_tcp.py:106`
- **Category**: Bug — Unreliable Validation / ICS Safety
- **Problem**: `assert self._writer is not None and self._reader is not None, "Not connected"`. Modbus TCP controls grid-connected hardware. An `AssertionError` stripped by `-O` leads to operating on `None` stream handles, causing unhandled `AttributeError` inside an async lock, which blocks the connection semaphore permanently. The same pattern appears in `vela/m2_protocols/dnp3.py:191,194,221,224,249,252,277,280,293`.
- **Fix**: Replace all `assert` guards on connection state with explicit `if not self._writer: raise ConnectionError("Not connected")`.

---

### [HIGH-11] No application-layer rate limiting — two implementations exist, neither is wired in; expensive endpoints are unprotected

- **File**: `vela/api/middleware.py:48` (`RateLimitMiddleware`), `vela/api/rate_limiter.py:55-98` (`RateLimiterRegistry` / `default_limiter`), `vela/api/app.py:25-30` (only `CORSMiddleware` is registered)
- **Category**: Security — Missing DoS / Abuse Protection (defense-in-depth gap)
- **Problem**: The codebase contains **two** complete rate-limiting implementations and wires in **neither**:
  - `RateLimitMiddleware` (sliding-window, 200 req/60s per IP) is fully implemented, but `create_app()` never calls `app.add_middleware(RateLimitMiddleware, ...)` — only `CORSMiddleware` is registered.
  - The standalone token-bucket `RateLimiterRegistry` / `default_limiter` in `rate_limiter.py` is never imported or used by any route.

  Edge rate limiting **does** exist and is active in the deployed topology: the nginx reverse proxy (`docker/nginx/nginx.conf:53-55`) enforces 100 r/s general + 10 r/s on auth + 50 connections/IP, and the k8s ingress (`k8s/ingress/vela-ingress.yaml:17-18`) sets `limit-rps: 100` / `limit-connections: 50`. So this is *not* "zero rate limiting" — but three real gaps make it a serious issue:

  1. **No defense-in-depth.** All enforcement lives outside the application. Any path that bypasses the edge — running `uvicorn` directly, internal service-to-service calls hitting the pod, `kubectl port-forward`, or a misconfigured/removed ingress — has **zero** rate limiting.
  2. **Expensive endpoints are unthrottled at the app layer.** `POST /v1/dispatch/run` performs CPU-bound MILP solves that block the event loop (see HIGH-4) and have no bounded solve time (see LOW-9). A flat 100 r/s IP limit does not stop a *low-volume* attacker from repeatedly invoking *expensive* endpoints — a handful of concurrent MILP requests can starve every API worker. This requires a per-endpoint / cost-weighted limit, which only an app-layer limiter (the dead `RateLimiterRegistry`) can provide.
  3. **No per-API-key / per-tenant quotas.** Edge limits are IP-keyed only and cannot enforce fairness or quotas per authenticated consumer.
- **Fix**:
  - Register `RateLimitMiddleware` in `create_app()` as a defense-in-depth layer, keyed on `request.client.host` (the real peer) rather than the spoofable `X-Forwarded-For` (see MEDIUM-12).
  - Add a tighter, cost-aware limit on `/v1/dispatch/run` and the other optimization/ML endpoints using `default_limiter` as a FastAPI dependency (smaller bucket per API key or asset group).
  - Keep the nginx/ingress limits as the volumetric edge defense; treat the app-layer limit as enforcement that travels with the service regardless of how traffic reaches it.
  - Fix the eviction bug in the registry (MEDIUM-10) before relying on it.

---

### [HIGH-12] `encryption.py` generates an ephemeral key when `VELA_ENCRYPTION_KEY` is not set — field-level encryption is useless

- **File**: `vela/security/encryption.py:21-29`
- **Category**: Security — Data at Rest Exposure
- **Problem**: When `VELA_ENCRYPTION_KEY` is absent, `Fernet.generate_key()` creates a random key that is discarded at process exit. Any encrypted data stored during one process run cannot be decrypted in the next. This silently produces corrupt/unreadable data in production without raising an error, and the warning message is at `logger.WARNING` level only.
- **Fix**: Raise a `RuntimeError` in production environments instead of generating an ephemeral key. Require the key to be set via the secrets manager.

---

### [HIGH-13] `AuditLog.log()` returns `None` instead of raising when severity is below threshold

- **File**: `vela/m14_cybersecurity/audit_log.py:123`
- **Category**: Bug — Incorrect Return Type / Null Dereference
- **Problem**: `return None  # type: ignore`. The return type annotation is `AuditRecord`, but callers receiving `None` can dereference it (e.g., `record.record_hash`). The `# type: ignore` comment suppresses the type error rather than fixing it. Any caller that acts on the return value without a None check will crash.
- **Fix**: Change the return type to `Optional[AuditRecord]` and add `if not self._should_log(severity): return None` without suppressing the type check. Update callers to handle `None`.

---

### [MEDIUM-1] CAISO OASIS base URL uses plain HTTP in `.env.example`

- **File**: `.env.example:29`
- **Category**: Security — Insecure Transport
- **Problem**: `CAISO_OASIS_BASE_URL=http://oasis.caiso.com/oasisapi/SingleZip` uses HTTP. Market price data and authentication credentials transmitted over unencrypted HTTP can be intercepted or tampered with.
- **Fix**: Change to `https://oasis.caiso.com/oasisapi/SingleZip`. The connector code in `vela/m1_ingestion/iso_connectors/caiso.py:14` already uses `https://`, but this env var creates a vector for misconfiguration.

---

### [MEDIUM-2] Grafana anonymous access is set to Admin role in dev docker-compose

- **File**: `docker/docker-compose.override.yml:98-99`
- **Category**: Security — Exposed Interface
- **Problem**: `GF_AUTH_ANONYMOUS_ENABLED: "true"` and `GF_AUTH_ANONYMOUS_ORG_ROLE: Admin`. If the dev compose is accidentally run against a shared or staging environment, every anonymous user gets full Grafana admin access including data source credentials.
- **Fix**: Change `GF_AUTH_ANONYMOUS_ORG_ROLE` to `Viewer`, or disable anonymous auth entirely in non-local dev environments.

---

### [MEDIUM-3] Redis and PostgreSQL in dev docker-compose have no passwords

- **File**: `docker/docker-compose.override.yml:62-68`, line 74
- **Category**: Security — Weak Credentials
- **Problem**: `POSTGRES_PASSWORD: vela` and Redis has `command: redis-server --loglevel verbose` with no `--requirepass`. Ports are forwarded to `localhost:5432` and `localhost:6379`. On developer machines shared via a corporate network or VPN, these are accessible to other network participants.
- **Fix**: Add `--requirepass <password>` to the Redis command. For Postgres, use a randomized password via Docker secrets or a local `.env` file. Use `127.0.0.1:5432:5432` instead of `5432:5432` to restrict to loopback.

---

### [MEDIUM-4] `forecast_cache.py` uses MD5 for cache key hashing

- **File**: `vela/cache/forecast_cache.py:25`
- **Category**: Security / Maintainability — Deprecated Crypto
- **Problem**: `hashlib.md5(raw.encode()).hexdigest()`. MD5 is cryptographically broken (collision attacks). While a cache key is non-security-critical, using MD5 is a code quality red flag that can mislead reviewers about the security properties of the system, and it may trigger security scanners/SAST tools.
- **Fix**: Use `hashlib.sha256` or `hashlib.blake2b` (faster and secure). Cache key collision probability with MD5 at this scale is low but non-zero.

---

### [MEDIUM-5] Webhook delivery silently swallows all exceptions

- **File**: `vela/api/routers/webhooks.py:161-162`
- **Category**: Error Handling — Swallowed Exception
- **Problem**: `except Exception: delivery.status = "failed"`. Any exception (network, serialization, DNS failure) is caught and discarded without logging. Operators cannot diagnose why webhook deliveries are failing.
- **Fix**: Add `logger.exception("Webhook delivery failed for %s: %s", hook.url, exc)` inside the `except` block.

---

### [MEDIUM-6] Email sender silently swallows SMTP exceptions

- **File**: `vela/m28_notifications/email_sender.py:87-88`
- **Category**: Error Handling — Swallowed Exception
- **Problem**: `except Exception: return False`. SMTP failures during critical alert delivery (e.g., grid fault notifications) are silently dropped. The caller receives `False` but has no information to decide whether to retry or escalate.
- **Fix**: Log the exception with full traceback: `logger.exception("SMTP send failed to %s", message.to)`.

---

### [MEDIUM-7] `MILPDispatchOptimizer.solve()` has an empty `finally: pass` block — wasted solve-time measurement

- **File**: `vela/m6_optimizer/milp.py:61-62`
- **Category**: Bug / Maintainability — Dead Code
- **Problem**: The `t0 = time.perf_counter()` at line 53 is computed in `solve()` but the `finally: pass` block that should record the elapsed time is empty. Actual solve time is only measured inside `_solve_highs()`. If `_solve_highs` raises any exception other than `ImportError`, `t0` is simply unused.
- **Fix**: Remove the dead `finally: pass` block and the orphaned `t0` computation in `solve()`.

---

### [MEDIUM-8] `SettlementEngine.calculate()` uses `datetime.utcnow()` (deprecated) for default timestamp

- **File**: `vela/m9_settlement/settlement_engine.py:110`
- **Category**: Bug — Deprecated API / Timezone Naivety
- **Problem**: `datetime.utcnow()` returns a timezone-naive datetime object. Python 3.12 deprecated `utcnow()`. If this naive datetime is compared to timezone-aware datetimes elsewhere in the system, a `TypeError` will be raised. Multiple files share this pattern (listed in MEDIUM-9).
- **Fix**: Replace with `datetime.now(timezone.utc)`.

---

### [MEDIUM-9] Widespread use of deprecated `datetime.utcnow()` across the codebase

- **File**: `vela/m8_market/ercot_ancillary.py:103`, `vela/m12_demand_response/program_registry.py:69`, `vela/m12_demand_response/event_manager.py:38,56,71,155,170`, `vela/cache/forecast_cache.py:21`, `vela/m9_settlement/pjm_settlement.py:66`, `vela/m9_settlement/models.py:70,102`, `vela/m9_settlement/ercot_settlement.py:88`
- **Category**: Bug — Deprecated API / Timezone Naivety
- **Problem**: These 11 occurrences of `datetime.utcnow()` produce naive datetimes that mix with timezone-aware ones from the rest of the system, causing potential `TypeError` in comparisons and incorrect time arithmetic.
- **Fix**: Perform a global replace: `datetime.utcnow()` → `datetime.now(timezone.utc)` (ensuring `timezone` is imported from `datetime`).

---

### [MEDIUM-10] Rate limiter eviction uses insertion-order assumption on `dict` — not LRU

- **File**: `vela/api/rate_limiter.py:72-74`
- **Category**: Bug — Incorrect Eviction Logic
- **Problem**: `for k in list(self._buckets.keys())[:evict_count]: del self._buckets[k]`. Python dicts preserve insertion order, so this evicts the *oldest created* buckets, not the *least recently used* ones. A low-traffic IP that connected first is evicted before a high-traffic IP that connected recently, defeating the purpose of the registry.
- **Fix**: Use `collections.OrderedDict` with move-to-end on access, or `functools.lru_cache`-style eviction. Alternatively, add timestamps and evict by last-access time.

---

### [MEDIUM-11] All API endpoints return synthetic random data in place of real values

- **File**: `vela/api/routers/telemetry.py:70-79`, `vela/api/routers/market.py:127-148`, `vela/api/routers/forecasts.py:52-62`, `vela/api/routers/bids.py:84-96`, `vela/api/routers/compliance.py:121-125`, `vela/graphql/resolvers.py:33-85`
- **Category**: Maintainability / Data Integrity — Stub Implementation
- **Problem**: The majority of API endpoints generate data via `numpy.random` or `random` with hardcoded seeds rather than querying databases or real data sources. A client application consuming these endpoints would receive fabricated data indistinguishable from real measurements. This pattern is not guarded by a feature flag or environment check, so it could be deployed as-is.
- **Fix**: Each endpoint should query the database (using `get_db()` session) or the appropriate service module. Add an explicit `NotImplementedError` or HTTP 501 response if real data is not yet available, so the incompleteness is visible.

---

### [MEDIUM-12] `RateLimitMiddleware` X-Forwarded-For header is trusted unconditionally — IP spoofing possible

- **File**: `vela/api/middleware.py:69-72`
- **Category**: Security — Header Spoofing
- **Problem**: `forwarded_for = request.headers.get("X-Forwarded-For")` is used as-is for rate limiting. An attacker can set this header to any IP, bypassing per-IP rate limits by rotating the spoofed IP address on each request.
- **Fix**: Only trust `X-Forwarded-For` when the request originates from a known trusted proxy (e.g., the nginx upstream). Use the `trusted_hosts` list or compare the actual connecting IP against a CIDR range of known proxies.

---

### [MEDIUM-13] `CryptoKey` stores raw key material in memory as a plain `bytes` field

- **File**: `vela/m14_cybersecurity/key_management.py:54`
- **Category**: Security — Sensitive Data Exposure
- **Problem**: `key_material: bytes` is stored in the `CryptoKey` dataclass. A comment says "In production: this would be a KMS reference, not plaintext." The `KeyStore._keys` dict holds all key material in plaintext in the process heap, accessible to any code that can reach the `KeyStore` instance, including memory dumps.
- **Fix**: As the comment suggests, in production this must be replaced with a KMS key reference (ARN, key ID). The `KeyStore` should only hold references and make API calls to KMS to perform cryptographic operations.

---

### [MEDIUM-14] `WebSocket` telemetry endpoint has no authentication check

- **File**: `vela/api/websocket.py:58-93`
- **Category**: Security — Missing Auth Check
- **Problem**: `@router.websocket("/ws/telemetry/{asset_id}")` accepts any connection without validating a token. WebSocket upgrade requests can carry `Authorization` headers or query-parameter tokens that should be verified before the connection is established.
- **Fix**: Check for a token in the query parameters (`?token=...`) or the first message after connect, validate it with `decode_access_token`, and close the WebSocket with code 4001 on failure.

---

### [MEDIUM-15] `EventBus.publish()` acquires a lock then calls handlers outside the lock — race condition

- **File**: `vela/m26_events/event_bus.py:61-89`
- **Category**: Bug — Race Condition
- **Problem**: The handlers list is copied while holding `self._lock`, then handlers are called without holding the lock. If a handler modifies the bus (subscribes or unsubscribes), those modifications are thread-safe, but if a handler itself publishes events, recursive lock acquisition via `threading.RLock` is needed and the handler list snapshot may be stale. More critically, the dead-letter `with self._lock:` inside the handler loop re-enters the lock for each failure, creating contention.
- **Fix**: The current snapshot approach is correct for the subscription race, but document the threading model. Move the dead-letter append outside the lock or use a separate lock for the dead-letter queue to reduce contention.

---

### [MEDIUM-16] `TrainingPipeline.train()` ignores the `model_fn` parameter and always uses `SimpleLinearModel`

- **File**: `vela/m20_ml/training_pipeline.py:127-183`
- **Category**: Bug / Maintainability — Dead Parameter
- **Problem**: The `model_fn: Optional[Callable]` parameter is accepted but never used. The pipeline always instantiates `SimpleLinearModel`. Callers passing an XGBoost, LSTM, or random-forest factory will silently get a linear model instead.
- **Fix**: Use `model_fn() if model_fn else SimpleLinearModel(...)` or remove the parameter and document that only `SimpleLinearModel` is supported.

---

### [LOW-1] `ModelRegistry` training-data hash is computed with Python's built-in `hash()` — non-deterministic across processes

- **File**: `vela/m20_ml/model_registry.py:100`
- **Category**: Bug — Non-Determinism
- **Problem**: `hex(hash(training_start + training_end))[:12]`. Python's `hash()` is randomized per-process via `PYTHONHASHSEED`. The same training date range will produce different hashes in different runs, making model lineage tracking unreliable and the hash useless for reproducibility checks.
- **Fix**: Use `hashlib.sha256((training_start + training_end).encode()).hexdigest()[:12]`.

---

### [LOW-2] `CAISO._parse_lmp()` defines `get()` as a closure inside a loop — late binding bug

- **File**: `vela/m1_ingestion/iso_connectors/caiso.py:61-63`
- **Category**: Bug — Python Closure / Late Binding
- **Problem**: `def get(tag: str) -> str:` is redefined inside `for row in root.findall(...)`. In Python, a nested function defined inside a loop captures the loop variable by reference. While `get` here doesn't directly close over `row`, redeclaring the function on every iteration is wasteful. The same pattern appears in `_parse_ancillary()` at line 114 and `fetch_system_load()` at line 155.
- **Fix**: Define the `get` helper once outside the loop as a `lambda` or standalone function that takes both `row` and `tag` as arguments.

---

### [LOW-3] `Celery` broker and backend URLs are hardcoded to `localhost` in `celery_app.py`

- **File**: `vela/workers/celery_app.py:6-8`
- **Category**: Maintainability / Portability — Hardcoded URL
- **Problem**: `broker="redis://localhost:6379/0"`, `backend="redis://localhost:6379/1"`. These URLs ignore `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` environment variables defined in `.env.example`. Deploying to any non-localhost environment (Docker, Kubernetes, staging) will silently fail to connect.
- **Fix**: `broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")` and similarly for backend.

---

### [LOW-4] `dispatch.py` router runs the optimizer with hardcoded demo asset parameters

- **File**: `vela/api/routers/dispatch.py:72`
- **Category**: Maintainability — Stub Implementation
- **Problem**: `assets = [Asset(asset_id=aid, capacity_mwh=4.0, power_mw=2.0) for aid in req.asset_ids]`. Real asset specifications (actual capacity, efficiency, SOC limits) are not fetched from the asset registry. Every dispatched asset is treated as a 4 MWh / 2 MW battery regardless of what was registered.
- **Fix**: Query `AssetModel` from the database for each `asset_id` before constructing optimizer inputs.

---

### [LOW-5] `SMTPConfig` stores password as a plain string field in a dataclass

- **File**: `vela/m28_notifications/email_sender.py:32`
- **Category**: Security / Maintainability — Sensitive Data in Memory
- **Problem**: `password: str = ""`. The SMTP password is stored as a plain Python string in a dataclass that could be serialized, logged, or inspected via `dataclasses.asdict()`. It is also printed in `repr()` unless overridden.
- **Fix**: Use a `SecretStr` type (from Pydantic or a custom wrapper) that suppresses the value in `repr` and `str` calls.

---

### [LOW-6] `SCADABridge.poll()` silently swallows callback exceptions

- **File**: `vela/m27_integrations/scada_bridge.py:103-105`
- **Category**: Error Handling — Swallowed Exception
- **Problem**: `except Exception: pass`. Telemetry callbacks that raise are silently discarded. In an ICS context this can mask critical data processing errors.
- **Fix**: Add `logger.exception("Telemetry callback error for point %s", point.point_id)`.

---

### [LOW-7] Prometheus `--web.enable-lifecycle` is enabled in production compose without authentication

- **File**: `docker/docker-compose.prod.yml:113`
- **Category**: Security — Exposed Admin Interface
- **Problem**: `--web.enable-lifecycle` allows HTTP `POST /-/reload` and `POST /-/quit` which can stop or reconfigure Prometheus from any network host that can reach the container's port. In the compose setup there is no authentication on Prometheus.
- **Fix**: Remove `--web.enable-lifecycle` from production, or put Prometheus behind the nginx proxy with basic auth.

---

### [LOW-8] `TrainingPipeline` silently uses only `SimpleLinearModel` regardless of `algorithm` in `TrainingConfig`

- **File**: `vela/m20_ml/training_pipeline.py:152,159`
- **Category**: Bug / Maintainability — Configuration Ignored
- **Problem**: `self.config.algorithm` (which could be `"xgboost"`, `"lstm"`, `"random_forest"`) is stored but never used to select the model class. All training runs use ridge regression.
- **Fix**: Implement an algorithm dispatch map or raise `NotImplementedError` for unsupported algorithms.

---

### [LOW-9] `SecurityAnalysis` and MILP optimizer solve times are not bounded

- **File**: `vela/m6_optimizer/milp.py`, `vela/orchestrator/loop.py:167`
- **Category**: Performance — Unbounded Computation
- **Problem**: `MILPDispatchOptimizer.solve()` calls `h.run()` with no time limit parameter. The `OptimizerConfig.solve_time_limit_seconds = 30.0` is defined but never passed to the HiGHS solver. For large fleets or long horizons, the solve can run indefinitely, blocking the dispatch cycle.
- **Fix**: Pass `h.setOptionValue("time_limit", solve_time_limit_seconds)` before calling `h.run()`.

---

### [LOW-10] `ingest_all_markets()` runs connectors sequentially despite the coroutine setup

- **File**: `vela/m1_ingestion/pipeline.py:101-119`
- **Category**: Performance — Sequential Instead of Parallel
- **Problem**: `tasks` is constructed as a dict of coroutines, but they are awaited sequentially in a `for market, coro in tasks.items(): results[market] = await coro` loop. The docstring says "concurrently" but this is actually serial — N markets × round-trip latency.
- **Fix**: Use `asyncio.gather(*tasks.values())` and match results back to market names via `zip(tasks.keys(), results)`.

---

### [LOW-11] `AdminRouter._audit()` actor defaults to `"system"` — not the actual user

- **File**: `vela/api/routers/admin.py:91,110,125`
- **Category**: Maintainability / Audit Integrity
- **Problem**: `_audit("system", "create_user", ...)` and `_audit("system", "deactivate_user", ...)` hard-code `"system"` as the actor. When real authentication is added, these should record the authenticated user's ID so the audit trail is meaningful.
- **Fix**: Pass the current user's ID (obtained from `CurrentUser`) to `_audit()` in each route handler.

---

## Summary Table of Files With the Most Issues

| File | Issues |
|------|--------|
| `vela/api/app.py` | CRITICAL-1 (via auth.py), CRITICAL-2, CRITICAL-3 |
| `vela/api/auth.py` | CRITICAL-1, HIGH-5 |
| `vela/api/dependencies.py` | HIGH-2 |
| `vela/api/middleware.py` | HIGH-11, MEDIUM-12 |
| `vela/api/routers/dispatch.py` | HIGH-4, HIGH-7, LOW-4 |
| `vela/api/routers/webhooks.py` | HIGH-3, MEDIUM-5 |
| `vela/api/routers/admin.py` | HIGH-6, HIGH-7, LOW-11 |
| `vela/api/routers/telemetry.py` | HIGH-7, MEDIUM-11 |
| `vela/api/websocket.py` | MEDIUM-14 |
| `vela/m2_protocols/ieee2030_5.py` | CRITICAL-4 |
| `vela/m2_protocols/modbus_tcp.py` | HIGH-10 |
| `vela/m6_optimizer/milp.py` | MEDIUM-7, LOW-9 |
| `vela/m9_settlement/settlement_engine.py` | HIGH-8, MEDIUM-8 |
| `vela/m14_cybersecurity/audit_log.py` | HIGH-13 |
| `vela/m14_cybersecurity/key_management.py` | MEDIUM-13 |
| `vela/m20_ml/training_pipeline.py` | MEDIUM-16, LOW-8 |
| `vela/m26_events/event_bus.py` | MEDIUM-15 |
| `vela/graphql/schema.py` | HIGH-1 |
| `vela/workers/celery_app.py` | LOW-3 |
| `vela/security/encryption.py` | HIGH-12 |
| `vela/cache/forecast_cache.py` | MEDIUM-4, MEDIUM-9 |
| `docker/docker-compose.override.yml` | MEDIUM-2, MEDIUM-3 |
| `docker/docker-compose.prod.yml` | LOW-7 |

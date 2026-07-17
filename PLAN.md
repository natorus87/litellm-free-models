# PLAN.md — Code Review Findings & Remediation Plan

> ✅ **RESOLVED on 2026-07-16** — All findings 1–10, minor findings 1–6, and
> improvement suggestions V1–V15 have been implemented (V15 as a documented
> positioning decision, V13 as a budgets/docs solution, since the
> Prometheus callback is enterprise-gated in current LiteLLM OSS
> versions). Details: AGENTS.md §7/§8. This file remains as a review
> record.

> **As of: 2026-07-06** — Full code review of the uncommitted changes
> (Redis cache integration in Docker Compose & K8s, removal of
> `gemma-3-12b-it` and `qwen3-next-80b-a3b`, a second provider for the
> LLM7.io models, fallback updates, doc adjustments).
>
> Method: 8 independent review angles (line scan, removed behavior,
> cross-file tracing, reuse, simplification, efficiency, altitude,
> conventions), followed by one verifier pass per deduplicated candidate.
> **All 10 main findings were CONFIRMED** (finding 6 empirically verified
> via a `redis-cli` test inside the container).

---

## Priority 1 — Password Management (Security)

### Finding 1: Multi-instance Compose ignores configured Redis passwords

**File:** `multi-instance/docker-compose.yaml:56` (+ healthcheck line 67, `environment:` blocks lines 89/121/154)

`REDIS_PASSWORD` from the per-instance `.env` files (`master/.env`,
`slave1/.env`, `slave2/.env`) has no effect: Docker Compose interpolates
`${REDIS_PASSWORD:-…}` **at parse time** only from the shell environment
or the project-directory `.env` (`multi-instance/.env`) — never from a
per-service `env_file`. On top of that, the explicit `environment:`
entries override env_file values anyway.

**Failure scenario:** A user follows the comments in the `.env.example`
files ("Must match REDIS_PASSWORD on master, slave1, slave2…") and sets
a strong password in all three files. No `multi-instance/.env` exists
(the setup docs don't mention one) → Redis starts with
`--requirepass change-me-redis-password`, and all containers also get
the default. The configured password is silently ignored; the shared
cache runs with a publicly known default password.

**Suggested fix:**
- Introduce a `multi-instance/.env.example` with `REDIS_PASSWORD`
  (Compose automatically reads the project `.env`) and remove the
  misleading comments from the three per-instance `.env.example` files.
- Alternatively, fail hard instead of falling back to a default:
  `${REDIS_PASSWORD:?REDIS_PASSWORD must be set}`.

### Finding 2: `make k8s-apply` overwrites the Redis secret with the default password

**File:** `Makefile:73` + `k8s/redis-secret.yaml` + `k8s/deployment.yaml:50-63`

Three related problems:
1. `make k8s-apply` unconditionally applies the **committed,
   directly-appliable** `k8s/redis-secret.yaml` with
   `stringData.redis-password: "change-me-redis-password"` — overwriting
   any strong password an operator set via `kubectl create secret`
   (exactly as the file's own header instructs).
2. This breaks the repo convention: `litellm-secrets` is never
   committed, but generated at deploy time via
   `make k8s-secret --from-env-file=.env`; only `*.template` files are
   committed.
3. The new explicit `env:` entry in `k8s/deployment.yaml` pulls
   `REDIS_PASSWORD` via `secretKeyRef` from `litellm-redis-secret` and
   thereby **overwrites** the value coming from
   `envFrom`/`litellm-secrets` via `.env` (explicit `env:` takes
   precedence over `envFrom`) — password rotation via `.env` +
   `make k8s-secret` never has any effect.

**Failure scenario:** An operator creates `litellm-redis-secret` with a
strong password, later rolls out a config change via `make k8s-apply`
→ the secret gets reset to the default; after pod restarts,
WRONGPASS/NOAUTH on every cache and auth-cache call, i.e. production
silently runs with the published default password.

**Suggested fix:**
- Rename `k8s/redis-secret.yaml` → `k8s/redis-secret.yaml.template`
  (convention) and remove it from `k8s-apply`.
- Integrate the Redis password into the existing `make k8s-secret` flow
  (e.g. `kubectl create secret … --from-literal=redis-password=$$REDIS_PASSWORD`
  from `.env`), or source `REDIS_PASSWORD` directly from
  `litellm-secrets` and drop the separate secret entirely.

### Finding 3: K8s probes can never detect Redis auth errors

**File:** `k8s/redis-deployment.yaml:53-72` (identical in `multi-instance/k8s/redis-deployment.yaml`)

The liveness/readiness probes call `redis-cli -a $(REDIS_PASSWORD) ping`.
Kubelet expands `$(VAR)` in **probe exec commands** only for env vars
with a static `value:` — `secretKeyRef` variables stay the literal
string `$(REDIS_PASSWORD)` (a known upstream issue,
kubernetes/kubernetes#40846; in container `args`, on the other hand,
the expansion works, so `redis-server` itself does get the real
password).

**Empirically verified** (redis:7-alpine): the probe authenticates with
the literal string, gets NOAUTH on the PING — and `redis-cli` still
exits with 0 without `-e`. **The probes are always green and validate
nothing.** A Redis instance with a broken secret/password is never
detected.

**Suggested fix:**
```yaml
exec:
  command:
    - sh
    - -c
    - redis-cli -a "$REDIS_PASSWORD" -e ping
```
(The shell expands the real env var; `-e` makes the exit code ≠ 0 on
error replies.)

---

## Priority 2 — Operational Risks

### Finding 4: The Redis pod gets OOMKilled as soon as the cache fills up

**File:** `k8s/redis-deployment.yaml:46-52` (identical in `multi-instance/k8s/redis-deployment.yaml`)

`resources.limits.memory: 256Mi` is **exactly equal** to
`--maxmemory 256mb` (Redis parses the `mb` suffix as binary) — zero
headroom for allocator fragmentation, client buffers, and the
copy-on-write pages of the BGSAVE fork (`--save 60 100` = a snapshot
every minute). `requests.memory: 128Mi` is even below maxmemory.

**Failure scenario:** Once the LRU cache fills up to ~256mb, the next
BGSAVE fork under write load pushes RSS over the cgroup limit →
kubelet OOMKills the pod, **all** LiteLLM instances simultaneously lose
the shared response and auth cache, and the pod crash-loops under
load.

**Suggested fix:** Raise the limit to ≥ 2× maxmemory (e.g. `512Mi`) — or
better: `--save ""` (no persistence; an LRU cache is disposable and
re-warms itself), which also eliminates the fork COW, the 5Gi PVC, and
the `redis-data` volumes (see minor findings).

### Finding 5: Unconditional `cache: true` breaks `make check-config` and `make docker-run`

**File:** `config.template.yaml:958-974` + `Makefile:35-40, 109-116`

The cache block with `os.environ/REDIS_*` is **unconditionally**
hardcoded into the single-source-of-truth template. Every consumer of
the rendered `config.yaml` outside the updated Compose/K8s stacks now
depends on an unreachable Redis:

- `make check-config`: a bare `docker run` with only the config
  mounted (no REDIS_* env, no Redis) → the cache client falls back to
  localhost, `/health/readiness` reports unhealthy — the documented
  validation target fails for a valid config.
- `make docker-run`: `--env-file .env` with `REDIS_HOST=redis`,
  unresolvable outside the Compose network → connection-error spam and
  latency on every request and every virtual-key lookup
  (`enable_redis_auth_cache`).

LiteLLM doesn't fail hard here, it degrades (lazy connect, errors
logged per request).

**Suggested fix:** `render-config.py` already has the appropriate
conditional mechanism (`filter_blocks` removes provider blocks when
API keys are empty): render the cache block analogously only if
`REDIS_HOST` (or a dedicated `ENABLE_REDIS_CACHE`) is set.
Additionally, either pass the REDIS_* variables into `check-config` and
`docker-run`, or explicitly render those without the cache.

### Finding 6: A global response cache is a silent behavior change

**File:** `config.template.yaml:958-974`

With `cache: true`, `ttl: 3600`, and `acompletion` in
`supported_call_types`, **identical requests return the byte-identical
cached response for an hour** — across the master and all slaves.
LiteLLM hashes the call kwargs (model, messages, temperature, …) as
the cache key; an intentional re-roll with the same parameters
(temperature > 0) therefore hits the cache.

The opt-out (`"cache": {"no-cache": true}` or the Cache-Control header)
is a LiteLLM extension outside the OpenAI API — standard clients and
coding agents don't send it. The "live-validated via `GET /cache/ping`"
documented in AGENTS.md only checks connectivity, not this semantics.

**Suggested fix:** Make a deliberate decision and document it. Options:
significantly lower the TTL, use the cache only for auth
(`enable_redis_auth_cache`) and disable response caching, or
prominently document the behavior + opt-out in the README and
AGENTS.md.

### Finding 7: `REDIS_PORT` appears configurable but is ignored

**File:** `docker-compose.yaml:34-44, 86` (analogous in `multi-instance/docker-compose.yaml`)

`.env.example` lists `REDIS_PORT=6379` as a variable, the proxy
containers get `REDIS_PORT=${REDIS_PORT:-6379}`, and the config uses
`port: os.environ/REDIS_PORT` — but the redis command never sets
`--port`, Redis always listens on 6379.

**Failure scenario:** A user sets `REDIS_PORT=6380` → all proxies dial
`redis:6380`, connection refused on every cache operation. The
healthcheck runs inside the Redis container against localhost:6379 and
stays green — the failure is silent.

**Suggested fix:** Add `--port "${REDIS_PORT:-6379}"` to the redis
command (command + healthcheck) — or remove the variable from the
.env files and document the port as fixed.

### Finding 8: `find-shared-models.py` hardcodes the removed `gemma-3-12b-it`

**File:** `find-shared-models.py:964-965`

The auto-apply logic, when no `"*"` key exists in the fallbacks, inserts
a catch-all chain that contains `gemma-3-12b-it` — but this model was
completely removed in this diff. `render-config.py`'s
`remove_orphaned_fallbacks` only validates fallback **keys**, never
chain **targets**, and explicitly exempts `"*"` — the dangling target
would be passed through.

**Failure scenario:** If the `"*"` entry is ever removed from the
template, `find-shared-models.py --apply` reinserts a fallback to a
model_name with zero deployments → a routing error instead of falling
back to `deepseek-v4-flash`/`openrouter-free`. Currently dormant (the
"`"*"` exists" guard holds), but live.

**Suggested fix:** Update the hardcoded chain to the current models
(`gemma-4-26b-a4b-it` instead of `gemma-3-12b-it`) — better yet:
generally validate chain targets against the model_list at render
time.

---

## Priority 3 — Documentation

### Finding 9: AGENTS.md is internally inconsistent

**File:** `AGENTS.md`

- **Lines 94 + 97:** `llama-3.3-70b-instruct` appears twice in the
  deployment matrix (once as "5-6" with OVHcloud, once as "5" without)
  — 23 lines for a claimed 22 model_names. Line 97 is the stale
  duplicate leftover and should be deleted.
- **Lines 50, 179, 204:** old numbers (118/70/24) contradict section 3,
  which was updated in this diff (22 model_names, 59 base + 44 slave =
  103).
- **Lines 150-168:** the fallback example block still references the
  removed `gemma-3-12b-it` and `qwen3-next-80b-a3b` — anyone who copies
  it reintroduces fallbacks to nonexistent model_names.
- **Lines 183, 196:** "14 variables"/"all 14 keys" (actual: 20 incl.
  REDIS_*); the file-structure section doesn't list the new
  `redis-*.yaml` files.

### Finding 10: README.md and multi-instance/README.md not updated in sync

**Files:** `README.md`, `multi-instance/README.md`

- `README.md` lines 107, 168, 316: still say "24 model_names / 70
  deployments"; line 32: "24+ models".
- `README.md` line 178: lists the removed `gemma-3-12b-it`; line 188:
  `qwen3-next-80b-a3b`.
- `README.md` lines 192-195: lists the LLM7.io models as single-provider,
  even though this diff adds a second provider for each.
- `multi-instance/README.md` lines 25-27, 33, 37, 135, 221, 231: still
  say "118 deployments" (actual: 103).

**Failure scenario:** Users request documented but removed models
(these now only run through the `"*"` catch-all or error out);
operators who see 103 instead of 118 deployments after regeneration
suspect a broken generation run instead of the intended model removal.

---

## Minor Findings (below the top-10 cut, all verified)

1. **TTL comment contradicts the value** — `config.template.yaml:966`:
   the comment says "5 min for in-memory tier", the value set is
   `default_in_memory_ttl: 60` (= 1 min). The "5 min" presumably belongs
   to `user_api_key_cache_ttl: 300`.
2. **`GEMINI_API_KEY` is dead configuration** — after removing
   `gemma-3-12b-it`, no deployment uses `{{GEMINI_API_KEY}}` anymore,
   but the key is still injected/documented (docker-compose.yaml:75,
   .env.example:67, both k8s secret templates, README provider table).
   `find-shared-models.py` doesn't hard-require it (skips google-ai when
   the key is missing) — clean it up or mark it as "for future syncs".
3. **A 5Gi PVC + RDB persistence for a 256mb LRU cache** —
   `k8s/redis-pvc.yaml` (×2) and `--save 60 100`: minutely fork+disk
   writes for disposable cache data; ~95% of the volume permanently
   unused. Simpler: `--save ""` + emptyDir, drop the PVC files and
   volume references.
4. **`supported_call_types` with dead entries** — `aembedding`/
   `atranscription` are listed even though all 69 deployments are
   `mode: chat`.
5. **Byte-identical Redis manifests duplicated** — `k8s/redis-*.yaml`
   vs. `multi-instance/k8s/redis-*.yaml`: same namespace, same resource
   names (`litellm-redis`, `redis-data`, `litellm-redis-secret`) → both
   apply paths overwrite each other, tuning changes drift apart. The
   kustomization already references `../namespace.yaml` and could use
   `../../k8s/redis-*.yaml`. (Postgres is deliberately NOT duplicated —
   a convention break here.)
6. **`#version: "3.9"`** in `docker-compose.yaml:1` commented out
   instead of deleted; an identical 3-line Redis comment is duplicated
   in `multi-instance/k8s/secret.yaml.template` (lines 96-99 + 130-133).

---

## Further Improvement Suggestions (outside the review scope)

Repo-wide points that came up during follow-up — independent of the
current diff, but partly directly connected to it.

### V1: `make test` masks test failures — CI can never turn red

**File:** `Makefile:145, 148` + `.github/workflows/ci.yml:44`

`python3 -m unittest discover -s tests -v 2>&1 | tail -5` — the exit
code of the target is `tail`'s (always 0), not unittest's; `make` uses
`/bin/sh` without `pipefail`. **Failing unit tests still let
`make test`, and therefore the CI job, pass green.**

**Fix:** `set -o pipefail` doesn't work in POSIX sh — instead, e.g.
`@python3 -m unittest discover -s tests -v 2>&1 | tail -5; exit $${PIPESTATUS[0]}`
with `SHELL := /bin/bash` in the Makefile, or simply run without
`| tail -5` (CI logs are allowed to be long).

### V2: `make check-config` is independently broken twice, unrelated to Redis

**File:** `Makefile:109-116`

1. `docker run` without `-p 4000:4000` → the subsequent
   `curl http://localhost:4000/health/readiness` can never reach the
   container; the target "validates" against nothing.
2. Every Make recipe line runs in its own shell: `kill %1` on line 116
   has no job table entry for the process started on line 111 →
   silently fails (`|| true`), and the container **keeps running
   orphaned**.

**Fix:** A single-line recipe with `docker run -d --name`,
`-p 4000:4000`, `curl --retry`, `docker rm -f` in a `trap`/cleanup — or
better: LiteLLM doesn't offer a real dry run, so do local YAML schema
validation (see V4) plus an optional smoke test.

### V3: CI exists but is toothless — and AGENTS.md denies it exists

**Files:** `.github/workflows/ci.yml`, `AGENTS.md` ("Open: ❌ No CI/CD")

- AGENTS.md lists "No CI/CD (lint/test pipeline)" as open — **stale**:
  `ci.yml` (test matrix 3.10-3.13, ruff, render dry run) and
  `sync-models.yml` already exist. Fix this together with the docs sync
  (finding 9).
- ruff is defanged twice over: `pip install ruff || true` and
  `ruff check . || echo "::warning::…"` — lint can never fail. Either
  make it blocking or remove it from CI (half-checks create false
  confidence).
- Combined with V1, CI effectively only checks that
  `render-config.py --dry-run` doesn't crash.

### V4: No validation of the K8s manifests and Compose files

There is no check that validates the 13 K8s YAMLs (+ multi-instance) or
the Compose files — exactly the file class in which this review found
the most errors.

**Suggestion:** Add to CI + pre-commit:
- `kubeconform`/`kubectl apply --dry-run=client` over `k8s/` and
  `multi-instance/k8s/` (would have caught e.g. schema errors),
- `docker compose config -q` for both Compose files (validates
  interpolation and syntax),
- `yamllint` is an obvious pre-commit addition.

### V5: Missing structural tests for the config invariants

`tests/` covers the scripts but not the template's invariants. Exactly
these would have caught several findings automatically:

- **Fallback targets exist**: every target in `fallbacks` /
  `context_window_fallbacks` is a model_name in the model_list (catches
  finding 8 and future model removals).
- **≥ 2-provider rule**: every model_name except the documented
  exceptions (OpenCode Zen, catch-all) has ≥ 2 deployments.
- **Docs sync**: count deployment numbers in AGENTS.md/README against
  the template (catches findings 9/10) — or better, generate the table
  (V8).

### V6: The rolling `main-latest` tag everywhere + `imagePullPolicy: IfNotPresent`

**Files:** `k8s/deployment.yaml:39-40`, both Compose files, `Makefile:112`

`ghcr.io/berriai/litellm:main-latest` is a daily-moving tag:
- Not reproducible — a redeploy can pull a different LiteLLM version
  than what was tested yesterday.
- With `IfNotPresent`, every node also gets stuck on a different
  version until the image is manually refreshed there.

**Suggestion:** Pin to a versioned tag (or digest) and pick up updates
via Dependabot/Renovate (Dependabot is already configured).

### V7: K8s security hardening is completely missing

**Files:** `k8s/*.yaml`, `multi-instance/k8s/**`

No container has a `securityContext` (runAsNonRoot,
readOnlyRootFilesystem, `capabilities: drop: [ALL]`, seccompProfile),
there's no NetworkPolicy (Redis + Postgres are reachable by any pod in
the namespace — relevant since Redis is only password-protected and
Postgres uses defaults), and no PodDisruptionBudget. The podAntiAffinity
in `k8s/deployment.yaml` is also ineffective at `replicas: 1` — either
raise the replica count (the Redis auth cache now makes that possible,
which is the point of the diff) or remove the affinity.

### V8: Generate the AGENTS.md model table instead of hand-maintaining it

The deployment matrix is hand-maintained and was already broken on its
first edit (finding 9). `find-shared-models.py` already parses the
template and knows the provider sets per model — an `--emit-matrix`
mode (markdown to stdout, or written directly into AGENTS.md/README
between marker comments) keeps the numbers permanently correct.
Similarly, drop the "X variables" counts.

### V9: The same default-password weakness for Postgres

**Files:** `docker-compose.yaml` (`POSTGRES_PASSWORD:-litellm`), K8s Postgres

The review pattern from findings 1/2 also pre-existingly applies to
Postgres: default credentials `litellm/litellm` as a fallback in the
DATABASE_URL. While reworking the password flow (step 1), bring
Postgres along too (`:?` interpolation or generated secrets).

### V10: Minor hygiene items

- **Backup inflation**: 10× `config.yaml.bak.*` in the working directory
  (gitignored, but clutter) — a `make clean` target or auto-prune to
  the last N backups in `render-config.py`.
- **`make k8s-secret` dumps the entire `.env`** (incl. comment context
  of all 20 variables) into `litellm-secrets` — works, but an explicit
  key allowlist would prevent local extra variables from ending up in
  the cluster secret.
- **Prometheus annotations** without a documented scrape setup/
  ServiceMonitor — either document or remove.
- **`.dockerignore`/`Dockerfile`**: check whether `config.yaml` (real
  keys!) could accidentally get copied into the build image — the
  `docker-build` path builds from the repo root.

### V11: Auto model update — raise the sync workflow from report to PR pipeline

**Files:** `.github/workflows/sync-models.yml`, `find-shared-models.py`, `.opencode/skill/sync-free-models/`

**Current state:** The weekly workflow only produces an artifact
(`providers-overlap.txt`, 7-day retention) — no `--apply`, no PR, no
notification. And it runs **without provider keys**:
`find-shared-models.py` skips providers with a missing key
("Missing key"), so the CI report is systematically incomplete.
Effectively, the auto-update path only exists as a manual OpenCode
skill (`sync-free-models`).

**Suggestion — staged automation (never auto-merge):**
1. **Store provider keys as GitHub secrets** (free-tier keys,
   least-privilege; only the read-only catalog queries need them), so
   the report can even become complete.
2. **PR instead of artifact:** on detected changes, run
   `find-shared-models.py --apply` + `render-config.py` +
   `multi-instance/generate-config.py` and open a PR via
   `peter-evans/create-pull-request` — overlap report as the PR
   description, provider diff as the changelog.
3. **Gates in the same workflow:** the invariant tests from V5
   (fallback targets exist, ≥ 2-provider rule), `make test` (after the
   V1 fix), manifest/compose validation from V4. Only green PRs reach
   the reviewer.
4. **Docs in the same PR:** use the matrix generator from V8 to
   automatically regenerate AGENTS.md/README — the drift from findings
   9/10 then can no longer happen.
5. **Flapping protection:** catalogs wobble (models appear/disappear
   week to week, cf. gemma-3-12b-it). Only propose removals once a
   model has been missing for N consecutive runs (state e.g. as a
   committed status file or via a cache artifact); propose new
   additions immediately, flag removals conservatively and loudly in
   the PR.
6. **Fallback without keys:** if secrets are missing, open an issue or
   fail the run instead of silently producing an incomplete report —
   today's mode (a quiet, gap-ridden report) is the worst option.

**Risks/limits:** free-tier keys in CI are a (small) leak risk — use
separate keys just for the sync; catalog API rate limits on the weekly
run are uncritical. No auto-merge stays off: model changes affect
routing/fallbacks and need a human look.

### V12: The biggest unused Redis opportunity — rate-limit-aware routing

**File:** `config.template.yaml:911` (`routing_strategy: simple-shuffle`)

The diff introduces Redis but only uses it for response and auth
caching. The core problem of a **free-tier** proxy, however, is
provider rate limits — and that's exactly where Redis stays unused:

- `simple-shuffle` picks deployments at random and **completely ignores
  the `tpm`/`rpm` values maintained in the template**. The 59
  deployments with carefully documented limits (rpm: 1 for OpenRouter
  up to rpm: 40 for LLM7) get equal traffic — an rpm:1 deployment gets
  as much traffic as an rpm:40 deployment and constantly runs into
  429s, which are then only absorbed via retries/fallbacks.
- With `routing_strategy: usage-based-routing-v2` + Redis in
  `router_settings` (redis_host/port/password analogous to
  cache_params), LiteLLM tracks tpm/rpm usage **cross-instance**
  (master + slaves + replicas!) and routes to deployments that still
  have budget — including shared cooldowns across all instances.
- While doing this, check: `tpm`/`rpm` sit at the deployment top level
  in the template (siblings of `litellm_params`) — for router
  awareness they belong under `litellm_params.tpm`/`litellm_params.rpm`.
  With simple-shuffle the difference doesn't show; it becomes relevant
  on a strategy switch.

This would be the point where the current diff's Redis effort pays off
the most functional value — more than the response cache (finding 6
shows it's even a double-edged sword).

### V13: Observability & alerting — nothing configured

**Files:** `config.template.yaml` (no callbacks/alerting), `k8s/deployment.yaml:20-22`

There are no `success_callback`/`failure_callback`, no alerting, no
budgets at all. For a proxy whose whole purpose is squeezing free
tiers, that means missing exactly the visibility into: which providers
are throwing 429s? Which deployments are in cooldown? What's the
fallback rate?

- **Metrics:** configure the Prometheus callback (check whether it's
  included in the OSS tier of the pinned LiteLLM version — it was
  temporarily enterprise-gated); alternative: spend logs already live
  in Postgres → point a Grafana dashboard directly at the DB. The
  existing `prometheus.io/scrape` annotations are currently just
  decoration (cf. V10).
- **Alerting:** LiteLLM webhook alerting (e.g. Slack/Discord) for
  provider outages, cooldown clusters, and DB errors.
- **Budgets/limits per virtual key:** use `max_budget`,
  `tpm_limit`/`rpm_limit` per key so a single consumer can't drain all
  free tiers for everyone else.

### V14: Postgres is the only persistent state — and has no backup

**Files:** `k8s/postgres-pvc.yaml`, both Compose files

Virtual keys, spend tracking, and team/user mappings live exclusively
in Postgres. There's neither a backup mechanism (pg_dump CronJob,
volume snapshots) nor a documented restore procedure; in Compose,
everything hangs off a local Docker volume. A broken PVC/volume means:
all issued API keys are gone, all clients need new keys. Minimal
solution: a daily `pg_dump` as a K8s CronJob into a second PVC (or
object storage) + a restore section in the README. (The Redis PVC, on
the other hand, can go away — see minor finding 3.)

### V15: Architecture question — does the master/slave setup need to exist at all?

**Files:** `multi-instance/**`

The multi-instance setup exists to use 3 API keys per provider (3×
rate limit). But LiteLLM can hold **multiple deployments of the same
provider with different keys in a single instance** — the same 59
base deployments simply 3× with key1/key2/key3 would give the same
effect without: a second config pipeline (`generate-config.py`), 3
proxy containers, the master hop (latency + double auth),
SLAVE?_API_KEY management, and the whole multi-instance/ duplication
(cf. minor finding 5). With V12 (usage-based routing), the keys would
even be balanced limit-aware.

**The only genuine justification for separate instances:** providers
with **IP-based** limits (OVHcloud: 2 RPM per IP, anonymous) — these
only benefit if the instances run on separate egress IPs. In a
single-cluster K8s setup (one NAT/egress), the master/slave setup
brings nothing there either way. Recommendation: decide and document —
either multi-key deployments in one instance (simplification), or
deliberately position multi-instance only for separate hosts/IPs.

---

## Suggested Remediation Order

| Step | Findings | Effort |
|---|---|---|
| 1. Fix the password flow (Compose project .env, secret-template convention, resolve env precedence; bring Postgres along) | 1, 2, V9 | medium |
| 2. Fix probes (`sh -c` + `-e`) | 3 | small |
| 3. Harden Redis operations (`--save ""` or a 512Mi limit; settle the PVC question) | 4, minor finding 3 | small |
| 4. Render the cache conditionally + fix the `check-config`/`docker-run` targets | 5, V2 | medium |
| 5. Decide and document cache behavior | 6 | small |
| 6. Make `REDIS_PORT` consistent | 7 | small |
| 7. Update the `find-shared-models.py` hardcoding | 8 | small |
| 8. Sync the docs (AGENTS.md incl. CI status, READMEs) | 9, 10, minor findings 1, 2, V3 | medium |
| 9. Cleanup (manifest duplicates, dead config) | minor findings 4-6 | small |
| 10. Harden tests/CI (`make test` exit code, blocking ruff, manifest validation, invariant tests) | V1, V3, V4, V5 | medium |
| 11. Harden the deployment (image pinning, securityContext, NetworkPolicy, replicas/PDB) | V6, V7 | medium |
| 12. Tooling convenience (matrix generator, make clean, secret key allowlist) | V8, V10 | small |
| 13. Auto model-update pipeline (sync workflow → PR with gates, flapping protection, docs regeneration) | V11 | medium-large (builds on 10 + 12) |
| 14. Rate-limit-aware routing via Redis (usage-based-routing-v2, tpm/rpm under litellm_params) | V12 | medium |
| 15. Observability, budgets & Postgres backup | V13, V14 | medium |
| 16. Architecture decision: multi-instance vs. multi-key deployments | V15 | evaluation |

# LiteLLM Free-Models Proxy

A [LiteLLM](https://github.com/BerriAI/litellm) proxy that aggregates **exclusively free LLM APIs** from 13 providers — with automatic load balancing, cooldown, and fallback chains. The same model (e.g. `gpt-oss-120b`) is covered by multiple providers to bypass individual free-tier rate limits.

![Tests](https://img.shields.io/badge/tests-89_passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![LiteLLM](https://img.shields.io/badge/litellm-proxy-orange)

---

## Table of Contents

- [Features](#-features)
- [Quickstart](#-quickstart)
- [Architecture](#-architecture)
- [Providers](#-providers)
- [Models](#-models)
- [Configuration](#-configuration)
- [Response Cache](#-response-cache)
- [Backup & Restore](#-backup--restore)
- [Observability & Budgets](#-observability--budgets)
- [Tests](#-tests)
- [Development](#-development)
- [Sync Workflow](#-sync-workflow)
- [Multi-Instance](#-multi-instance)
- [Contributing](#-contributing)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## ✨ Features

- **13 providers, 22 models** — OpenRouter, Cerebras, Groq, Cloudflare Workers AI, Google AI Studio, NVIDIA NIM, Mistral, Cohere, GitHub Models, OpenCode Zen, LLM7.io, HuggingFace Inference API, OVHcloud.
- **Rate-limit-aware load balancing** — `usage-based-routing-v2` routes to deployments that still have `tpm`/`rpm` budget (a 1-RPM OpenRouter deployment no longer receives as much traffic as a 40-RPM NVIDIA one). With Redis, usage and cooldowns are tracked **across all instances/replicas**.
- **Fallback chains** — each model has a prioritized list of fallbacks (e.g. `gpt-oss-120b` → `gpt-oss-20b` → `llama-3.3-70b-instruct`).
- **Shared Redis cache** — response cache (5 min TTL, see [Response Cache](#-response-cache)) + virtual-key auth cache across replicas. Fully optional: without `REDIS_HOST` the config renders Redis-free.
- **Anonymous OVHcloud tier** — the 13th provider runs **without an API key** (2 RPM/IP/model) and is ready to use out of the box.
- **Live pricing report** — `find-shared-models.py` shows hypothetical savings vs. paid-tier prices (LiteLLM reference DB).
- **Multi-instance setup** — Master + 2 Slaves in `multi-instance/` triple the effective rate limits (for separate hosts/IPs, see [Multi-Instance](#-multi-instance)).
- **Template pipeline** — `config.template.yaml` is the single source of truth; `render-config.py` renders `config.yaml` from it with `{{ENV_VAR}}` substitution, provider filtering, and fallback-target validation.
- **89 unit tests** — including structural invariant tests (fallback targets must exist, ≥ 2-provider rule).

---

## 🚀 Quickstart

**Easiest path — guided onboarding** (creates `.env`, generates passwords, walks you through API keys with sign-up URLs, live-checks the keys, renders the config, and starts Docker Compose):

```bash
git clone https://github.com/<your-user>/litellm-free-models.git
cd litellm-free-models
make onboard          # or: python3 onboard.py
```

The script is safe to re-run any time — after adding a new API key, rotating passwords, or to re-render and restart the stack. The manual steps below do the same thing piece by piece.

### 1. Clone the repository

```bash
git clone https://github.com/<your-user>/litellm-free-models.git
cd litellm-free-models
```

### 2. Create `.env`

```bash
cp .env.example .env
nano .env
```

**Required:** `REDIS_PASSWORD` and `POSTGRES_PASSWORD` must be set (e.g. `openssl rand -hex 16`) — docker-compose refuses to start with empty passwords instead of silently falling back to a published default.

**Note on API keys:** Most keys are **optional** — the proxy runs with only a subset of providers. `OPENROUTER_API_KEY` is the most important exception: without it, the `openrouter-free` model is removed from all fallback chains (otherwise you'd get 401 errors). `OVHCLOUD_API_KEY` may be **left empty** for the anonymous free tier.

See `.env.example` for sign-up URLs and additional context.

### 3. (Optional) Python dependencies

The pipeline uses only the Python standard library — no `pip install` is required. To validate the LiteLLM server locally, however, you will need Docker.

### 4. Render the configuration

```bash
make render-config          # or: python3 render-config.py
```

This step generates `config.yaml` from `config.template.yaml`, replaces `{{ENV_VAR}}` placeholders with values from `.env`, and removes provider blocks whose key is not set.

### 5. Start the proxy

```bash
make docker-compose-up      # or: docker compose --env-file .env up -d
```

The proxy listens on **port 4444** (locally: `http://localhost:4444`) and uses LiteLLM's internal port 4000.

### 6. Test request

```bash
curl http://localhost:4444/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss-120b",
    "messages": [{"role": "user", "content": "Say hello in German."}]
  }'
```

Response: JSON object with `choices[0].message.content` (OpenAI-compatible format).

---

## 🏗️ Architecture

### Single Instance (main setup)

```
                  ┌─────────────────────────────────────────┐
                  │       LiteLLM Proxy (:4000 internal)    │
                  │     Routing: usage-based-routing-v2     │
   Client ──────► │     22 model_names, 69 deployments      │
   (Port 4444)   │     Cooldown 30s, Retries 2             │
                  └────────────┬────────────────────────────┘
                               │
        ┌──────────┬───────────┼───────────┬──────────┬────────┐
        ▼          ▼           ▼           ▼          ▼        ▼
   OpenRouter  Cerebras     Groq      Cloudflare   NVIDIA  OVHcloud
   (1 RPM)     (30 RPM)  (2-30 RPM)  (10 RPM)   (40 RPM)  (2 RPM)
                                                          (no key!)
        +  Google AI, Mistral, Cohere, GitHub Models,
           OpenCode Zen, LLM7.io, HuggingFace
```

### Multi-Instance (3× rate limit)

In the [`multi-instance/`](multi-instance/README.md) directory an additional master/slave setup runs:

```
                  ┌──────────────────────────────────┐
                  │   MASTER (:4000, own keys)       │
   Client ──────► │   69 direct + 44 slave backends  │
                  └──────────────┬───────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
         ┌────────────┐   ┌────────────┐   ┌────────────┐
         │ Direct     │   │ SLAVE 1    │   │ SLAVE 2    │
         │ (own       │   │ :4001      │   │ :4002      │
         │  keys)     │   │ (other     │   │ (other     │
         │            │   │  keys)     │   │  keys)     │
         └────────────┘   └────────────┘   └────────────┘
```

Effectively **3× rate limit per provider** (master + 2 slaves with different accounts). Detailed instructions in [`multi-instance/README.md`](multi-instance/README.md).

---

## 📋 Providers

| #  | Provider                | Auth          | RPM (Free)      | Env-Var(s)                                      | Notes |
|----|-------------------------|---------------|-----------------|-------------------------------------------------|-------|
| 1  | OpenRouter              | API Key       | 1               | `OPENROUTER_API_KEY`                            | Catch-all `openrouter-free` |
| 2  | Cerebras                | API Key       | 30              | `CEREBRAS_API_KEY`                              | `llama3.1-8b` deprecated (2026-05-27) |
| 3  | Groq                    | API Key       | 2-30            | `GROQ_API_KEY`                                  | Model-dependent |
| 4  | Cloudflare Workers AI   | API Token     | 10              | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_API_BASE`    | Suffix `-fp8-fast` |
| 5  | Google AI Studio        | API Key       | 2               | `GEMINI_API_KEY`                                | Currently no active deployment (gemma-3 series retired); key kept for future syncs |
| 6  | NVIDIA NIM              | API Key       | 40              | `NVIDIA_API_KEY`                                | OpenAI-compatible, Kimi = `moonshotai/kimi-k2-instruct` |
| 7  | Mistral La Plateforme   | API Key       | 2               | `MISTRAL_API_KEY`                               | Phone verification required |
| 8  | Cohere                  | API Key       | 20              | `COHERE_API_KEY`                                | Trial key, 1000 calls/month |
| 9  | GitHub Models           | PAT           | 15              | `GITHUB_TOKEN`                                  | Scope: `models:read`, Azure endpoint |
| 10 | OpenCode Zen            | API Key       | 10              | `OPENCODE_ZEN_API_KEY`                          | Free models: `deepseek-v4-flash-free`, `big-pickle` |
| 11 | LLM7.io                 | API Key       | 40 (with token) | `LLM7IO_API_KEY`                                | `unused` works for the base tier |
| 12 | HuggingFace Inference   | API Token     | 30              | `HF_TOKEN`                                      | 150K+ models via `huggingface/<org>/<model>` |
| 13 | OVHcloud AI Endpoints   | **no key**    | 2 (anonymous)   | `OVHCLOUD_API_KEY` (optional/empty)             | Anonymous free tier, IP limit |

Sign-up URLs for the keys: see comments in [`.env.example`](.env.example).

---

## 🤖 Models

<!-- BEGIN GENERATED MODEL MATRIX (python3 find-shared-models.py --write-docs) -->
Stand (aus `config.template.yaml` generiert): **22 model_names, 69 base-Deployments**. `render-config.py` entfernt Deployments von Providern ohne API-Key in `.env` – die effektive Anzahl kann daher kleiner sein.

| model_name | Deployments | Provider |
|---|---|---|
| `gpt-oss-120b` | 7 | OpenRouter, Cerebras, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace |
| `gpt-oss-20b` | 6 | OpenRouter, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace |
| `llama-3.3-70b-instruct` | 6 | OpenRouter, Groq, Cloudflare, GitHub Models, OVHcloud, HuggingFace |
| `llama-3.1-8b` | 5 | Groq, Cloudflare, NVIDIA, GitHub Models, HuggingFace |
| `deepseek-v4-flash` | 4 | OpenRouter, NVIDIA, OpenCode Zen, HuggingFace |
| `llama-4-maverick` | 4 | Groq, OpenRouter, NVIDIA, HuggingFace |
| `llama-4-scout` | 4 | Groq, Cloudflare, GitHub Models, HuggingFace |
| `gemma-4-26b-a4b-it` | 3 | OpenRouter, Cloudflare, HuggingFace |
| `gemma-4-31b-it` | 3 | OpenRouter, NVIDIA, HuggingFace |
| `kimi-k2.6` | 3 | OpenRouter, Cloudflare, NVIDIA |
| `nemotron-3-120b` | 3 | OpenRouter, Cloudflare, NVIDIA |
| `nemotron-3-nano-30b` | 3 | OpenRouter, NVIDIA, HuggingFace |
| `nemotron-3-ultra` | 3 | OpenRouter, OpenCode Zen, NVIDIA |
| `codestral-latest` | 2 | LLM7.io, Mistral |
| `command-r-plus` | 2 | Cohere, GitHub Models |
| `deepseek-r1-0528` | 2 | LLM7.io, HuggingFace |
| `mistral-large` | 2 | Mistral, GitHub Models |
| `mistral-small-3.2` | 2 | LLM7.io, Mistral |
| `qwen3-235b` | 2 | LLM7.io, HuggingFace |
| `big-pickle` | 1 | OpenCode Zen |
| `north-mini-code` | 1 | OpenCode Zen |
| `openrouter-free` | 1 | OpenRouter |
<!-- END GENERATED MODEL MATRIX -->

The table above is **generated** from `config.template.yaml` via `python3 find-shared-models.py --write-docs` — do not edit it by hand (CI checks for drift).

---

## ⚙️ Configuration

The configuration runs through a **template pipeline**:

```
config.template.yaml   (single source of truth, in the repo)
        │
        │  python3 render-config.py
        ▼
config.yaml            (generated, in .gitignore)
        │
        ├─► LiteLLM container (mounted)
        └─► multi-instance/generate-config.py
```

`config.template.yaml` contains `{{ENV_VAR}}` placeholders (e.g. `{{OPENROUTER_API_KEY}}`) and a comment header per provider. `render-config.py` performs five steps:

1. **Substitution** — `{{ENV_VAR}}` → value from `.env`. Missing keys become empty strings.
2. **Block filter** — If a *required* key is missing, the entire provider block (including the comment header) is removed from `model_list`. OVHcloud is the exception and accepts an empty key.
3. **Redis blocks** — The cache block (`litellm_settings`) and the router-tracking block (`router_settings`) are only rendered when `REDIS_HOST` is set in `.env` (and `--no-redis` is not passed). Without Redis, the proxy runs cache-free instead of degrading against an unreachable Redis.
4. **OpenRouter-free fallback** — If `OPENROUTER_API_KEY` is set, `openrouter-free` is appended to every fallback chain and to the catch-all `*`. If the key is missing, the entry is removed again (otherwise 401).
5. **Fallback validation** — Fallback entries whose *key* points to a removed `model_name` are deleted, and chain *targets* that no longer exist in the `model_list` are filtered out.

Writes are atomic with a timestamped backup of the previous version (`config.yaml.bak.<timestamp>`, the last 5 are kept). Direct edits to `config.yaml` are **overwritten** on the next render — changes always belong in the template.

Related scripts:

- `find-shared-models.py` — Live provider sync + pricing report (see [Sync Workflow](#-sync-workflow))
- `providers_config.py` — Central provider definitions (env-var names, API format, RPM, API URLs)
- `multi-instance/generate-config.py` — Master/slave config generator

### Kubernetes secrets

`make k8s-secret` creates three secrets from your local `.env`:

- `litellm-secrets` — provider API keys (explicit allowlist; local extra variables never leak into the cluster)
- `litellm-redis-secret` — `redis-password` (used by both the Redis pod and the LiteLLM pods)
- `litellm-postgres-secret` — `postgres-password`

Password rotation: change `.env`, run `make k8s-secret`, then `make k8s-restart`. The committed `*.template` files only document the expected shape and are **never applied** by `make k8s-apply` — a committed default can therefore never overwrite a real password.

---

## 🗄️ Response Cache

With `REDIS_HOST` set, LiteLLM caches **responses** in Redis. This is a deliberate trade-off you should know about:

- LiteLLM hashes the call kwargs (`model`, `messages`, `temperature`, …) as the cache key. **Identical requests return the byte-identical cached answer within the TTL — even with `temperature > 0`.** An intentional re-roll with the same parameters hits the cache.
- The TTL is deliberately short (**5 minutes**, `ttl: 300` in `config.template.yaml`) to bound this effect while still absorbing bursts/retries.
- Per-request opt-out (LiteLLM extension, not part of the OpenAI API — standard clients do not send it):

```json
{ "model": "gpt-oss-120b", "messages": [...], "cache": {"no-cache": true} }
```

or the `Cache-Control: no-cache` header. To disable response caching entirely, remove `REDIS_HOST` from `.env` (auth caching and cross-instance rate-limit tracking are then disabled too) or delete the cache block from the template.

Redis itself runs as a pure LRU cache **without persistence** (`--save ""`): cache data is disposable and re-warms itself, so there are no BGSAVE forks and no PVC.

---

## 💾 Backup & Restore

Postgres is the **only persistent state** (virtual keys, spend tracking, team/user mappings). Losing it means all issued API keys are gone.

**Docker Compose:**

```bash
make backup-db     # pg_dump (custom format) into ./backups/
make restore-db    # restore the newest dump
```

**Kubernetes:** `make k8s-apply` installs a nightly CronJob (`k8s/postgres-backup-cronjob.yaml`, 03:30 UTC) that writes `pg_dump` files to a dedicated PVC and keeps the last 7. Restore:

```bash
# List available dumps
kubectl -n litellm-free-models create job --from=cronjob/postgres-backup backup-now  # optional: fresh dump first
kubectl -n litellm-free-models run pg-restore --rm -it --restart=Never \
  --image=postgres:16-alpine \
  --env="PGPASSWORD=<postgres-password>" \
  --overrides='{"spec":{"containers":[{"name":"pg-restore","image":"postgres:16-alpine","stdin":true,"tty":true,"command":["sh"],"volumeMounts":[{"name":"backups","mountPath":"/backups"}]}],"volumes":[{"name":"backups","persistentVolumeClaim":{"claimName":"postgres-backups"}}]}}'
# in the pod:
#   pg_restore -h postgres -U litellm -d litellm --clean /backups/litellm-<timestamp>.dump
```

---

## 📈 Observability & Budgets

Recommendations for operating the proxy (nothing is force-enabled by default):

- **Per-key budgets/limits** — prevent one consumer from draining all free tiers for everyone else. When creating virtual keys, set `max_budget`, `tpm_limit`, `rpm_limit`:

  ```bash
  curl -X POST http://localhost:4444/key/generate \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d '{"key_alias": "team-a", "rpm_limit": 30, "tpm_limit": 100000}'
  ```

- **Spend/usage data** lives in Postgres (`LiteLLM_SpendLogs`); a Grafana dashboard pointed directly at the DB is the simplest option. LiteLLM's Prometheus callback is enterprise-gated in recent versions — check your pinned version before relying on it.
- **429/cooldown visibility** — `GET /health` and the LiteLLM admin UI show deployment health; cooldown events appear in the proxy logs.

---

## 🧪 Tests

```bash
make test                # 89 unit tests, ~1s
```

The suite covers five modules:

- `tests/test_render_config.py` — substitution, block filter, OpenRouter-free logic
- `tests/test_find_shared_models.py` — overlap grouping, pricing cache
- `tests/test_providers_config.py` — provider metadata consistency
- `tests/test_multi_instance.py` — master/slave generator
- `tests/test_config_invariants.py` — structural invariants of the template: every fallback target exists in the `model_list`, ≥ 2-provider rule, `tpm`/`rpm` inside `litellm_params`, Redis markers balanced

The tests use only the Python standard library (`unittest`).

---

## 🛠️ Development

| Command                                                  | Purpose                                                |
|----------------------------------------------------------|--------------------------------------------------------|
| `make help`                                              | List all targets with a short description              |
| `make onboard`                                           | Guided interactive setup (keys, passwords, render, compose start) — re-runnable |
| `make render-config`                                     | Render `config.template.yaml` → `config.yaml`          |
| `make render-config-dry`                                 | Dry run (no write)                                     |
| `make render-config-no-redis`                            | Render without Redis blocks (standalone runs)          |
| `make check-config`                                      | Boot LiteLLM against a Redis-less render and check `/health/readiness` |
| `make validate-manifests`                                | Validate Compose files + K8s manifests (kubeconform)   |
| `make k8s-apply`                                         | Deploy everything to Kubernetes (namespace, secrets, configmap, deployments, backup cronjob) |
| `make k8s-secret`                                        | Create `litellm-secrets`, `litellm-redis-secret`, `litellm-postgres-secret` from `.env` |
| `make k8s-delete`                                        | Remove everything from Kubernetes                      |
| `make k8s-logs`                                          | Stream pod logs                                        |
| `make docker-compose-up` / `make docker-compose-down`    | Control docker-compose                                 |
| `make docker-build` / `make docker-run`                  | Build / run the custom image (standalone, without Redis) |
| `make backup-db` / `make restore-db`                     | Dump / restore the Compose Postgres DB (`./backups/`)  |
| `make test`                                              | Run 89 unit tests                                      |
| `make lint` / `make format`                              | Run ruff linter / formatter                            |
| `make clean`                                             | Remove generated/temporary files (backups, reports)    |
| `make install-dev`                                       | Install dev dependencies and pre-commit hooks          |
| `python3 find-shared-models.py --write-docs`             | Regenerate the model matrix in AGENTS.md/README.md     |
| `python3 find-shared-models.py`                          | Provider overlap report (dry run)                      |
| `python3 find-shared-models.py --apply`                  | Auto-apply: writes to the template + renders           |
| `python3 find-shared-models.py --apply --regen-multi-instance` | + Regenerate multi-instance configs             |
| `python3 find-shared-models.py --refresh-pricing`        | Reload LiteLLM pricing DB (24h cache)                  |
| `cd multi-instance && python3 generate-config.py`        | Generate master/slave configs                          |

---

## 🔄 Sync Workflow

When a provider adds new models, or a new model becomes available across multiple providers:

```bash
# 1. Live query of all providers + overlap report
python3 find-shared-models.py

# 2. Auto-apply: write missing deployments to the template,
#    update fallback chains, render config.yaml
python3 find-shared-models.py --apply

# 3. (Optional) Regenerate multi-instance configs
python3 find-shared-models.py --apply --regen-multi-instance

# 4. Review the diff
git diff

# 5. Run tests
make test

# 6. Commit
git add -A
git commit -m "sync: add <model> from <provider>"
```

The `find-shared-models.py` script:

1. Queries **all 13 providers live in parallel** (via the keys in `.env`; OVHcloud/LLM7/HF run without a key) with retry/backoff on transient errors.
2. **Filters to actually-free models**: OpenRouter is reduced to `:free`/zero-priced entries (so `--apply` can never introduce a paid model), Google AI to chat-capable models, Cohere to chat-capable model names; the HuggingFace catalog comes live from the Inference Router instead of a hardcoded list.
3. Normalizes model names and groups by overlap (≥ 2 providers), mapping groups back to the template's `model_names` so existing deployments are recognized instead of duplicated.
4. Compares hypothetical paid-tier prices from the LiteLLM reference DB (`https://models.litellm.ai/`, 24h cache in `.cache/`).
5. Reports **stale template deployments** whose model has disappeared from the provider's live catalog (report-only — removals stay manual).
6. With `--apply`, writes new deployment blocks to `config.template.yaml` — existing comments, RPMs, and cost fields are preserved.

More detailed docs on `find-shared-models.py` and output formats: [`AGENTS.md`](AGENTS.md) section 10.

**Automated:** the weekly GitHub Actions workflow [`sync-models.yml`](.github/workflows/sync-models.yml) runs the same sync with provider keys from `SYNC_*` repository secrets, regenerates the docs matrix, runs all gates (lint, tests, invariants, manifest validation) and opens a PR — never auto-merged. Without configured secrets the run fails loudly instead of producing a silently incomplete report.

---

## 📦 Multi-Instance

The [`multi-instance/`](multi-instance/README.md) directory contains a complete master/slave setup:

- **Master** with 113 deployments (69 direct + 44 slave backends)
- **2 Slaves** with 69 deployments each under different API keys
- Provider API keys per instance (`master/.env`, `slave1/.env`, `slave2/.env`); shared Redis/Postgres passwords in the project-level `multi-instance/.env`
- Dedicated docker-compose and Kubernetes manifests (`multi-instance/k8s/`)
- Kustomize setup for declarative deployment (Redis manifests are shared with the single-instance setup via the `k8s/redis/` base)

Prerequisite: **3 sets of API keys** (same providers, different accounts).

**When is this worth it?** LiteLLM can hold multiple deployments of the same provider with different keys **in a single instance** — same 3× rate-limit effect without a second config pipeline, three containers, and the master hop. The master/slave setup only adds value when the instances run on **separate hosts/egress IPs** (relevant for IP-based limits like OVHcloud's anonymous tier) or must be operated/owned separately. For a single host or a single K8s cluster (one NAT/egress IP), prefer multi-key deployments in one instance. Setup guide in [`multi-instance/README.md`](multi-instance/README.md).

---

## 🤝 Contributing

Contributions are welcome — whether new providers, new models, bug fixes, or documentation improvements. Please:

1. Open an issue or discussion first if the change is non-trivial.
2. Fork + feature branch.
3. `make test` must be green.
4. `make check-config` must succeed.
5. Open a PR with a meaningful description.

Details in [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## 📜 License

MIT — see [`LICENSE`](LICENSE).

---

## ⚠️ Disclaimer

This project aggregates **free tiers** from third parties. Free tiers can at any time:

- change their rate limits,
- deprecate or make models paid,
- be discontinued entirely.

There is **no guarantee for availability, response time, or model quality**. The proxy is intended as a tinkering/development tool — not for production. Assess the risk yourself before using it.

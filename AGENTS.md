# AGENTS.md — LiteLLM Free-Models Proxy

> **As of: 2026-08-19** — Full resolution of the 2026-07-06 code review
> (PLAN.md): password flow (Compose + K8s secrets from .env), conditional
> Redis rendering, `usage-based-routing-v2` with Redis tracking, manifest
> dedup (`k8s/redis/` base), CI with blocking lint + invariant tests +
> manifest validation, sync workflow as a PR pipeline, generated
> deployment matrix, Postgres backup, image pinning, securityContext +
> NetworkPolicy.

## Short Description

LiteLLM proxy that aggregates **exclusively free AI inference APIs** from 16 providers, with rate-limit-aware load balancing (`usage-based-routing-v2`), cooldowns, and fallback chains. The same chat models (e.g. `gpt-oss-120b`) are covered by multiple providers to work around rate limits; provider-specific aliases expose embeddings and audio transcription.

**Repo**: `/home/sb/github/litellm-free-models`

---

## 1. Architecture

### Single Instance (main setup)

```
Client ──► LiteLLM Proxy (:4000)
              │
              ├─► OpenRouter (1 RPM)
              ├─► Cerebras (30 RPM)
              ├─► Groq (2-30 RPM)
              ├─► Cloudflare Workers AI (10 RPM)
              ├─► Google AI Studio (2 RPM, currently no active deployment)
              ├─► NVIDIA NIM (40 RPM)
              ├─► Mistral La Plateforme (2 RPM)
              ├─► Cohere (20 RPM)
              ├─► Poolside (10 RPM conservative preview budget)
              ├─► Hetzner Experiments (5 RPM conservative best-effort budget)
              ├─► Z.AI (1 RPM conservative free-model budget)
              ├─► ElevenLabs (2 RPM conservative Scribe STT budget)
              ├─► OpenCode Zen (10 RPM)
              ├─► LLM7.io (40 RPM)
              ├─► HuggingFace Inference API (30 RPM)
              └─► OVHcloud (2 RPM, **no key needed**)
```

### Multi-Instance (extension in `multi-instance/`)

```
Client ──► MASTER (:4000, own keys + slave routing)
              │
              ├─► Direct providers (own API keys)
              ├─► Slave 1 (:4001, other API keys)
              └─► Slave 2 (:4002, other API keys)
```

Master (with every provider key configured): 157 direct + 142 slave deployments = **299 deployments**. Slaves reuse the base `config.yaml` via a Docker volume mount.

**Positioning (deliberate decision):** Multi-key deployments in ONE instance have the same 3× effect without the overhead. The master/slave setup is positioned only for **separate hosts/egress IPs** (IP-based limits like OVHcloud) — see the README section "Multi-Instance".

---

## 2. Providers & API Keys

| # | Provider | API Format | Env-Var | RPM (Free) |
|---|---|---|---|---|
| 1 | [OpenRouter](https://openrouter.ai) | openrouter/ | `OPENROUTER_API_KEY` | 1 |
| 2 | [Cerebras](https://cerebras.ai) | cerebras/ | `CEREBRAS_API_KEY` | 30 |
| 3 | [Groq](https://groq.com) | groq/ | `GROQ_API_KEY` | 2-30 |
| 4 | [Cloudflare Workers AI](https://workers.ai) | cloudflare/ | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_API_BASE` | 10 |
| 5 | [Google AI Studio](https://aistudio.google.com) | gemini/ | `GEMINI_API_KEY` (currently unused, kept for future syncs) | 2 |
| 6 | [NVIDIA NIM](https://build.nvidia.com) | openai/ (api_base) | `NVIDIA_API_KEY` | 40 |
| 7 | [Mistral La Plateforme](https://console.mistral.ai) | mistral/ | `MISTRAL_API_KEY` | 2 |
| 8 | [Cohere](https://cohere.com) | cohere/ | `COHERE_API_KEY` | 20 |
| 9 | [Poolside](https://poolside.ai/models) | openai/ (api_base) | `POOLSIDE_API_KEY` | 10* |
| 10 | [Hetzner Experiments](https://console.hetzner.com/) | openai/ (api_base) | `HETZNER_VLLM_API_KEY` | 5* |
| 11 | [Z.AI](https://z.ai/) | zai/ | `ZAI_API_KEY` | 1* |
| 12 | [ElevenLabs](https://elevenlabs.io/) | elevenlabs/ | `ELEVENLABS_API_KEY` | 2* |
| 13 | [OpenCode Zen](https://opencode.ai/zen) | openai/ (api_base) | `OPENCODE_ZEN_API_KEY` | 10 |
| 14 | [LLM7.io](https://llm7.io/) | openai/ (api_base) | `LLM7IO_API_KEY` | 40 |
| 15 | [HuggingFace Inference API](https://huggingface.co/) | huggingface/ | `HF_TOKEN` | 30 |
| 16 | [OVHcloud AI Endpoints](https://www.ovhcloud.com/en/public-cloud/ai-endpoints/) | openai/ (api_base) | (no key, anonymous free tier) | 2 |

Full env-var list including `REDIS_*`/`POSTGRES_*`: see `.env.example` (that file is the reference; numbers here are no longer hand-maintained).

### Provider Specifics

- **OpenRouter**: free chat catalog comes from `/api/v1/models`; free
  embeddings additionally come from `/api/v1/embeddings/models`. Embedding
  IDs participate in stale checks but are excluded from chat overlap/apply.
  Current NVIDIA aliases are `embedding-nvidia-text` and
  `embedding-nvidia-vl`, both live-tested at 2048 dimensions.
- **NVIDIA**: deployment name = `openai/openai/<model>` → sends `openai/<model>` to NVIDIA. Kimi runs under `moonshotai/kimi-k2-instruct` (different from `kimi-k2.6` on OpenRouter/Cloudflare).
- **GitHub Models**: retired by GitHub on 2026-07-30 and removed after live tests returned HTTP 404/410. The local `GITHUB_TOKEN` is no longer consumed.
- **Poolside**: OpenAI-compatible at `https://inference.poolside.ai/v1`; `poolside/laguna-s-2.1` is free for a limited time. Poolside does not publish preview limits, so the router uses a conservative 10 RPM / 200K TPM budget (`*`).
- **Hetzner Experiments**: OpenAI-compatible at `https://inference.hetzner.com/api/v1`; free, best-effort, and explicitly without production SLA. Configured aliases are `qwen3.6-35b-a3b` (`Qwen/Qwen3.6-35B-A3B-FP8`) and multimodal `qwen3.8-27b` (`Qwen/Qwen3.8-27B`), both with 262,144-token context advertised by Hetzner. Limits are unpublished, so routing starts at 5 RPM / 200K TPM (`*`).
- **Z.AI**: native LiteLLM `zai/` provider; free `glm-4.5-flash`, `glm-4.7-flash`, and vision-capable `glm-4.6v-flash`. The API omits these IDs from `/models` although they are callable. Limits are unpublished, so routing starts at 1 RPM / 100K TPM (`*`).
- **ElevenLabs**: native LiteLLM `elevenlabs/` provider; `scribe_v2` is a second deployment behind `audio-transcription`. Free-plan TTS cannot use premade/library voices and is therefore not routed. Free output is noncommercial; published output requires attribution.
- **OpenCode Zen**: endpoint `https://opencode.ai/zen/v1`, models: `deepseek-v4-flash-free`, `nemotron-3-ultra-free`, `big-pickle`, `north-mini-code-free`.
- **Cloudflare**: model suffix `-fp8-fast` instead of `-fp8` (verified against the API docs). `deepseek-v4-flash` doesn't exist on Cloudflare.
- **Cerebras**: `llama3.1-8b` was deprecated on 2026-05-27.
- **LLM7.io**: OpenAI-compatible at `https://api.llm7.io/v1`. Free tier: 2 RPM (40 RPM with a free token from token.llm7.io). `api_key: "unused"` for the base tier.
- **HuggingFace**: uses LiteLLM's `huggingface/` prefix → routes to the HF Inference API. Rate-limited, no credit card needed.
- **OVHcloud**: OpenAI-compatible at `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`. **Anonymous free tier** without an API key (2 RPM/IP/model). `api_key: ""` in `config.yaml`.
- **Google AI Studio**: currently **no active deployment** (Google retired the gemma-3 series, June 2026). `GEMINI_API_KEY` stays documented for future catalog syncs.

---

## 3. Models & Deployment Matrix

The matrix is **generated** (`python3 find-shared-models.py --write-docs`), not hand-maintained — CI checks for drift:

<!-- BEGIN GENERATED MODEL MATRIX (python3 find-shared-models.py --write-docs) -->
Snapshot (generated from `config.template.yaml`): **71 model_names, 157 base deployments**. `render-config.py` removes deployments from providers without an API key in `.env` — the effective count can therefore be lower.

| model_name | Deployments | Provider |
|---|---|---|
| `gpt-oss-20b` | 7 | OpenRouter, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace, LLM7.io |
| `gpt-oss-120b` | 6 | Cerebras, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace |
| `kimi-k2.6` | 6 | Cloudflare, NVIDIA, OpenCode Zen, LLM7.io, HuggingFace |
| `deepseek-v4-flash` | 5 | NVIDIA, OpenCode Zen, HuggingFace, LLM7.io |
| `gemma-4-31b-it` | 5 | OpenRouter, NVIDIA, HuggingFace, Cerebras, Google AI Studio |
| `deepseek-v4-flash-0731` | 4 | LLM7.io, HuggingFace, NVIDIA |
| `gemma-4-26b-a4b-it` | 4 | OpenRouter, Cloudflare, HuggingFace, Google AI Studio |
| `llama-3.3-70b-instruct` | 4 | Cloudflare, OVHcloud, HuggingFace, NVIDIA |
| `mimo-v2.5` | 4 | LLM7.io, HuggingFace |
| `kimi-k2.7-code` | 3 | OpenCode Zen, HuggingFace, LLM7.io |
| `kimi-k3` | 3 | OpenCode Zen, LLM7.io, HuggingFace |
| `laguna-s-2.1` | 3 | OpenRouter, OpenCode Zen, Poolside |
| `llama-3.1-8b` | 3 | Cloudflare, NVIDIA, HuggingFace |
| `nemotron-3-120b` | 3 | OpenRouter, Cloudflare, NVIDIA |
| `nemotron-3-nano-30b` | 3 | OpenRouter, NVIDIA, HuggingFace |
| `nemotron-3-ultra` | 3 | OpenRouter, OpenCode Zen, NVIDIA |
| `qwen3.6-27b` | 3 | Groq, HuggingFace, OVHcloud |
| `audio-transcription` | 2 | Groq, ElevenLabs |
| `codestral-latest` | 2 | LLM7.io, Mistral |
| `deepseek-r1-0528` | 2 | LLM7.io, HuggingFace |
| `deepseek-v3` | 2 | LLM7.io, HuggingFace |
| `deepseek-v4-pro` | 2 | OpenCode Zen, HuggingFace |
| `gemma-3-12b-it` | 2 | NVIDIA, HuggingFace |
| `gemma-3-4b-it` | 2 | NVIDIA, HuggingFace |
| `glm-5.2` | 2 | OpenRouter, NVIDIA |
| `gpt-oss-safeguard-20b` | 2 | Groq, HuggingFace |
| `inkling` | 2 | NVIDIA, HuggingFace |
| `kimi-k2.5` | 2 | OpenCode Zen, HuggingFace |
| `laguna-xs-2.1` | 2 | OpenRouter, NVIDIA |
| `llama-4-maverick` | 2 | NVIDIA, HuggingFace |
| `llama-4-scout` | 2 | Cloudflare, HuggingFace |
| `llama-guard-4-12b` | 2 | NVIDIA, HuggingFace |
| `lyria-3-clip` | 2 | OpenRouter, Google AI Studio |
| `lyria-3-pro` | 2 | OpenRouter, Google AI Studio |
| `minimax-m3` | 2 | NVIDIA, HuggingFace |
| `mistral-nemo-instruct-2407` | 2 | LLM7.io, OVHcloud |
| `nemotron-3-nano-omni-30b-a3b-reasoning` | 2 | OpenRouter, NVIDIA |
| `nemotron-3.5-content-safety` | 2 | OpenRouter, NVIDIA |
| `nemotron-3.5-lightning-free` | 2 | OpenRouter, OpenCode Zen |
| `nemotron-nano-12b-v2-vl` | 2 | OpenRouter, NVIDIA |
| `nemotron-nano-9b-v2` | 2 | OpenRouter, NVIDIA |
| `north-mini-code` | 2 | OpenCode Zen, OpenRouter |
| `qwen2.5-vl-72b-instruct` | 2 | HuggingFace, OVHcloud |
| `qwen3-235b` | 2 | LLM7.io, HuggingFace |
| `qwen3-32b` | 2 | HuggingFace, OVHcloud |
| `qwen3-coder-30b-a3b` | 2 | HuggingFace, OVHcloud |
| `qwen3.5-397b-a17b` | 2 | HuggingFace, OVHcloud |
| `qwen3.5-9b` | 2 | HuggingFace, OVHcloud |
| `step-3.7-flash` | 2 | NVIDIA, HuggingFace |
| `whisper-large-v3` | 2 | Groq, OVHcloud |
| `whisper-large-v3-turbo` | 2 | Groq, OVHcloud |
| `audio-speech` | 1 | Groq |
| `big-pickle` | 1 | OpenCode Zen |
| `command-r-plus` | 1 | Cohere |
| `dots-3-note-preview` | 1 | OpenRouter |
| `elevenlabs-scribe-v2` | 1 | ElevenLabs |
| `embedding-code` | 1 | Mistral |
| `embedding-general` | 1 | Google AI Studio |
| `embedding-liquid` | 1 | OpenRouter |
| `embedding-multilingual` | 1 | Cohere |
| `embedding-nvidia-text` | 1 | OpenRouter |
| `embedding-nvidia-vl` | 1 | OpenRouter |
| `glm-4.5-flash` | 1 | Z.AI |
| `glm-4.6v-flash` | 1 | Z.AI |
| `glm-4.7-flash` | 1 | Z.AI |
| `lfm-2.5-2.6b` | 1 | OpenRouter |
| `mistral-large` | 1 | Mistral |
| `openrouter-free` | 1 | OpenRouter |
| `qwen3-next-80b-a3b` | 1 | HuggingFace |
| `qwen3.6-35b-a3b` | 1 | Hetzner |
| `qwen3.8-27b` | 1 | Hetzner |
<!-- END GENERATED MODEL MATRIX -->

**Note on `gemma-3-12b-it`**: removed in June 2026 (Google retired the gemma-3 series; no free provider offers it anymore). Replacement: `gemma-4-26b-a4b-it` and `gemma-4-31b-it`.

**Provider-redundancy rule:** chat models require ≥ 2 deployments except the documented exceptions in `render-config.py`. `mistral-large`/`command-r-plus` lost GitHub Models; `qwen3-next-80b-a3b` lost its OpenRouter free route; the Z.AI Flash and current OpenRouter-only aliases have no second zero-price host. Provider-specific embedding aliases are exempt because vectors from different models cannot be mixed safely; their explicit empty fallback chains are enforced by `tests/test_config_invariants.py`.

### Multi-Instance (additional)

Master config (with every provider key configured): 157 base + 142 slave = **299 deployments**. Each slave reuses the rendered base config with its own keys → effectively 3× rate limit per provider.

---

## 4. Routing & Fallback

### Router Settings (config.template.yaml)

```yaml
router_settings:
  routing_strategy: usage-based-routing-v2   # rpm/tpm-budget-aware
  # redis_host/port/password (os.environ/REDIS_*) — only rendered if
  # REDIS_HOST is set; then cross-instance tracking + cooldowns
  num_retries: 1
  retry_after: 1
  allowed_fails: 1
  cooldown_time: 60
```

`tpm`/`rpm` live per-deployment in **`litellm_params`** (not top level!) so the router evaluates them. An invariant test enforces this. Load-tested GPT-OSS, Llama 3.3 70B, and Gemma 4 31B deployments use `timeout: 20`; embeddings use 15s, speech 60s, and transcription 120s. Every explicit tier uses `num_retries: 1`; unclassified chat models inherit the conservative 30s global ceiling.

### Fallback Chains

The authoritative source is `config.template.yaml` (`router_settings.fallbacks` / `context_window_fallbacks`) — examples are deliberately omitted here because copied snippets have reintroduced removed models in the past. Rules:

- Every chain target must be an existing model_name (invariant test + `render-config.py` additionally filters at render time).
- `openrouter-free` is automatically appended/removed at render time, depending on `OPENROUTER_API_KEY`.
- Catch-all `*` catches unknown model names.

---

## 5. File Structure

```
/home/sb/github/litellm-free-models/
├── onboard.py                   # Interactive setup (re-runnable): .env, key entry with
│                                #   sign-up URLs, live key check, render, compose start
├── opencode-config.py           # Create/update the provider entry in
│                                #   ~/.config/opencode/opencode.json (live models, schema-compliant options.*)
├── config.template.yaml         # Single source of truth with {{ENV_VAR}} + # BEGIN/END REDIS markers
├── config.yaml                  # Generated (gitignored, contains real keys)
├── render-config.py             # Renderer: substitution, provider filter, conditional Redis
│                                #   blocks, fallback key+target validation, --no-redis,
│                                #   backup of the previous version + auto-prune (last 5)
├── find-shared-models.py        # Catalog query, overlap report, --apply, --emit-matrix/--write-docs
├── providers_config.py          # Central provider definitions
├── .env.example                 # Template (passwords REQUIRED, shipped empty)
├── docker-compose.yaml          # Single instance (proxy + Redis + Postgres, :?-mandatory passwords)
├── Dockerfile                   # Optional custom image (⚠️ bundles config.yaml with real keys)
├── Makefile                     # render/check/validate/k8s/backup/clean targets, LITELLM_IMAGE pin
├── PLAN.md                      # 2026-07-06 review findings (basis of this resolution)
│
├── k8s/                         # Kubernetes (single instance)
│   ├── configmap.yaml           # Generated via make k8s-configmap (gitignored)
│   ├── deployment.yaml          # LiteLLM (pinned image, securityContext, DATABASE_URL)
│   ├── service.yaml / ingress.yaml / namespace.yaml
│   ├── networkpolicy.yaml       # Redis+Postgres reachable only from LiteLLM pods
│   ├── secret.yaml.template     # litellm-secrets (docs only; make k8s-secret creates the real one)
│   ├── postgres-secret.yaml.template
│   ├── postgres-{pvc,deployment,service}.yaml
│   ├── postgres-backup-{pvc,cronjob}.yaml   # Nightly pg_dump, 7-dump retention
│   └── redis/                   # SHARED Redis base (single AND multi instance)
│       ├── kustomization.yaml
│       ├── deployment.yaml      # --save "" (no PVC), 512Mi limit, sh -c probes with -e
│       ├── service.yaml
│       └── secret.yaml.template
│
├── tests/                       # 127 unit tests (unittest, stdlib-only)
│   └── test_config_invariants.py  # fallback isolation, chat ≥2-provider rule, tpm/rpm location, Redis markers
│
├── .github/workflows/
│   ├── ci.yml                   # ruff (blocking), test matrix, render smoke test,
│   │                            #   matrix drift check, compose config -q, kubeconform
│   └── sync-models.yml          # Weekly PR pipeline (SYNC_* secrets, gates, no auto-merge)
│
└── multi-instance/              # Master + 2 slaves
    ├── .env.example             # Project .env: REDIS_/POSTGRES_ passwords (Compose interpolation!)
    ├── master/ slave1/ slave2/  # per-instance .env.example (ONLY provider keys)
    ├── generate-config.py
    ├── docker-compose.yaml
    ├── k8s/                     # kustomization references ../../k8s/redis as a base
    └── README.md
```

---

## 6. Deployment

```bash
# Docker Compose (single instance)
make docker-compose-up          # renders + starts; REDIS_/POSTGRES_PASSWORD in .env REQUIRED

# Kubernetes (single instance)
make k8s-apply                  # namespace + secrets (from .env) + configmap + everything

# Multi-Instance
cd multi-instance
python3 generate-config.py
cp .env.example .env            # Redis/Postgres passwords (Compose reads ONLY these!)
# fill in master/slave .env files
docker compose up -d
```

---

## 7. Status & Known Limitations

### Completed (as of 2026-08-19)
- ✅ 16 providers integrated, 71 model_names / 157 template deployments
- ✅ Redis cache + auth cache, **conditionally rendered** (without REDIS_HOST → Redis-free)
- ✅ `usage-based-routing-v2` with Redis tracking; tpm/rpm in litellm_params
- ✅ Password flow: no more committed defaults; Compose enforces passwords (`:?`),
  `make k8s-secret` creates litellm-secrets (allowlist) + Redis/Postgres secrets from .env
- ✅ Redis: no persistence (`--save ""`), no PVC, limits with headroom, probes via `sh -c` + `-e`
- ✅ Manifest dedup: shared `k8s/redis/` base for both setups
- ✅ CI: ruff blocking, `make test` propagates exit codes, invariant tests,
  `docker compose config -q`, kubeconform, kustomize builds, matrix drift check
- ✅ Sync workflow → weekly PR pipeline with gates (no auto-merge, fails without secrets)
- ✅ Image pinned to `v1.97.0` (Makefile `LITELLM_IMAGE`, Compose, K8s, Dockerfile)
- ✅ securityContext everywhere, NetworkPolicies for Redis/Postgres
- ✅ Postgres backup: K8s CronJob (nightly, 7 dumps) + `make backup-db`/`restore-db` for Compose
- ✅ `make check-config` boots LiteLLM for real against a Redis-free render (port 4010)

### Open / Limitations
- ⚠️ Provider keys are local-only and availability varies; Z.AI Flash and
  ElevenLabs Scribe v2 were live-tested on 2026-08-19.
- ❌ `SYNC_*` GitHub secrets for the sync PR pipeline still need to be created
- ❌ Redis as a single pod without Sentinel/cluster (fine for a free-tier proxy)
- ❌ Multi-instance K8s has no own Postgres/DATABASE_URL (instances run DB-less there;
  deliberately not retrofitted — wire it up analogously to the single instance if needed)
- ⚠️ K8s Postgres was bumped from 15-alpine to 16-alpine (consistency with Compose).
  A PVC already initialized with PG15 won't start with PG16 — dump/restore beforehand.

---

## 8. Key Decisions

1. **Provider prefixes**: `openrouter/`, `cerebras/`, `groq/`, `cloudflare/`, `gemini/`, `zai/`, and `elevenlabs/` — routed automatically by LiteLLM. `openai/` for NVIDIA, Poolside, Hetzner, OpenCode Zen, LLM7.io, and OVHcloud, each with its own `api_base`.
2. **No PyYAML**: all generators/tests parse YAML line-based (stdlib-only).
3. **Slave config via volume mount**: slaves reference `../config.yaml`; only the master config gets generated.
4. **Reverse-proxy providers rejected**: Pollinations.ai, UncloseAI, G4F.dev (legality/reliability).
5. **Template as single source of truth**: edits only in `config.template.yaml`; `config.yaml` gets overwritten.
6. **OpenRouter-free fallback on/off** depending on `OPENROUTER_API_KEY` (renderer).
7. **Redis conditional** (`# BEGIN/END REDIS` markers): without `REDIS_HOST` (or with `--no-redis`), both the cache AND router Redis blocks are removed — no degrading against unreachable Redis. `make docker-run`/`check-config` use `--no-redis`.
8. **Response cache deliberately has a 300s TTL**: identical requests return the identical answer within 5 minutes (even with temperature > 0); opt-out via `{"cache": {"no-cache": true}}`. Documented in the README "Response Cache" section.
9. **Secret convention**: only `*.template` files are committed; real secrets are created by `make k8s-secret` from `.env` (litellm-secrets with an explicit key allowlist, litellm-redis-secret, litellm-postgres-secret). `k8s-apply` NEVER applies a secret file.
10. **Passwords without defaults**: Compose uses `${VAR:?}` interpolation; `.env.example` ships empty required fields. In multi-instance, Compose reads passwords ONLY from `multi-instance/.env` (per-service `env_file` is never used for interpolation).
11. **Redis is a pure cache**: `--save ""`, no PVC/emptyDir persistence — the cache re-warms itself; memory limit 512Mi = 2× maxmemory (fragmentation headroom).
12. **Image pinning**: `ghcr.io/berriai/litellm:v1.97.0` everywhere instead of `main-latest`; a central `LITELLM_IMAGE` variable in the Makefile; Dependabot (docker) bumps the Dockerfile, Compose/K8s then get updated manually. Since v1.9x, BerriAI tags stable releases as bare `vX.Y.Z` instead of `main-vX.Y.Z-stable`.
13. **usage-based-routing-v2 instead of simple-shuffle**: simple-shuffle completely ignored the maintained rpm/tpm values (rpm:1 OpenRouter got the same amount of traffic as rpm:40 NVIDIA). This required moving tpm/rpm into `litellm_params`.
14. **Docs matrix is generated** (`--write-docs` between HTML markers); CI fails on drift. Hand-maintained deployment counts are a thing of the past.
15. **Sync PR pipeline is conservative**: `--apply` only adds/updates costs; model removals stay manual (catalog flapping). Without `SYNC_*` secrets the run fails loudly.
16. **`opencode-config.py` writes schema-compliant output**: per the official schema (`https://opencode.ai/config.json` → `$defs.ProviderConfig`, `additionalProperties: false`), `apiKey`/`baseURL`/`timeout`/`chunkTimeout` live under `options`, not at the top level — an `apiKey` outside `options` is schema-invalid. When updating an existing provider entry, its `options.baseURL` is preserved unless `--host`/`--port`/`--base-url` is explicitly set (prevents a re-run from silently replacing a LAN-reachable address with the local default).
17. **Embedding aliases never cross-fallback**: `embedding-general` (Gemini, 3072d), `embedding-multilingual` (Cohere, 1024d), `embedding-code` (Codestral, 1536d), `embedding-nvidia-text` (2048d), multimodal `embedding-nvidia-vl` (2048d), and `embedding-liquid` (1024d) use explicit empty fallback chains so the generic chat catch-all cannot mix incompatible vector spaces. Embedding responses are eligible for the 300s Redis cache.
18. **Latency is tiered by workload**: load-tested `gpt-oss-120b`, `gpt-oss-20b`, `llama-3.3-70b-instruct`, and `gemma-4-31b-it` deployments use a 20s per-attempt timeout; embeddings use 15s, speech 60s, transcription 120s, and other chat models inherit 30s. Every tier gets one retry; the router waits 1s and cools a failed deployment for 60s. Load tests must use unique prompts plus `{"cache": {"no-cache": true}}`; repeated identical prompts only measure Redis latency.

---

## 9. Commands

```bash
# Onboarding (initial setup AND changes: keys, passwords, restart)
make onboard                    # interactive; --non-interactive for scripts

# Render & Validate
make render-config              # template -> config.yaml (Redis depending on REDIS_HOST)
                                # warns if a model_name has only 1 deployment left
make render-config-no-redis     # explicitly without Redis blocks
make check-config               # boots LiteLLM against a Redis-free render (port 4010)
make validate-manifests         # compose config -q + kubeconform (if installed)
make test                       # unit tests including invariants
make opencode-config            # create/update the provider entry in
                                # ~/.config/opencode/opencode.json (live models, options.timeout/chunkTimeout)
make lint / make format         # ruff
make clean                      # clean up backups/reports/caches

# Provider Overlap & Cost
python3 find-shared-models.py                   # report (dry run)
python3 find-shared-models.py --apply           # write into the template + render
python3 find-shared-models.py --apply --regen-multi-instance
python3 find-shared-models.py --emit-matrix     # deployment matrix to stdout
python3 find-shared-models.py --write-docs      # write the matrix into AGENTS.md/README.md

# Docker / K8s
make docker-compose-up / docker-compose-down
make docker-run                 # standalone without Redis (renders --no-redis, builds the image)
make k8s-apply / k8s-delete / k8s-secret / k8s-configmap / k8s-restart
make backup-db / restore-db     # dump/restore Compose Postgres to/from ./backups/

# Multi-Instance
cd multi-instance && python3 generate-config.py
docker compose up -d            # (first create .env + per-instance .envs)
kubectl apply -k k8s/           # K8s variant (uses ../../k8s/redis as a base)
```

---

## 10. Provider Overlap & Cost Check (Model Discovery)

`find-shared-models.py`:

1. **Live query** of 15 model catalogs via `.env` keys (`providers-overlap.txt`) — **in parallel** (ThreadPool, <2s instead of sequential) with **retry/backoff** on 429/5xx/network errors. OVHcloud/LLM7/HF also work without a key. ElevenLabs audio entitlement is validated separately because `/v1/models` does not list Scribe STT.
2. **Free-tier filter**: OpenRouter combines its chat and embedding catalogs and only returns `:free`/zero-priced models (embedding/rerank IDs are excluded from chat auto-apply); Google AI only keeps `generateContent`-capable models; Cohere only chat-capable model names; HuggingFace comes live from the Inference Router (`router.huggingface.co/v1/models`) instead of a hardcoded list (fallback list → provider gets marked "partial" and excluded from the stale check). Cloudflare is queried via `/ai/models/search` (paginated).
3. **Grouping** by normalized model names, filtered to ≥ 2 providers.
4. **Cost comparison** (hypothetical paid-tier price) from the LiteLLM reference DB, 24h cache under `.cache/litellm-prices.json`.
5. **Apply-plan mapping**: normalized group names are mapped onto the template's descriptive `model_names` (plus global dedup) — existing deployments are reliably recognized as `skip` instead of being planned as a duplicate. Provider detection in the template uses the api_base discrimination from `render-config.py` (NVIDIA/GitHub/Zen/LLM7/OVH share the `openai/` prefix).
6. **Stale-deployment detection** (the reverse of the apply plan): template deployments whose model is missing from the live catalog end up in their own report section ("Orphaned template deployments") — **report-only**, removals stay manual. Checked only against catalogs that were fetched successfully AND completely. Example find: the OVHcloud ID `Meta-Llama-3_3-...` (underscore) was mistakenly written with a dot in the template.
7. `--apply` writes new deployments into the template (tpm/rpm in litellm_params!) and renders.
8. `--emit-matrix`/`--write-docs` generate the docs matrix (§3).

**Important insight:** `input_cost_per_token`/`output_cost_per_token` in the report show the _paid-tier_ price; in `config.yaml` the model_info costs stay documentary — routing remains free-tier.

**Automated:** `.github/workflows/sync-models.yml` runs the same sync weekly with `SYNC_*` secrets and opens a PR (gates: ruff, tests, render, kubeconform; never auto-merged).

---

## 11. Template Pipeline (`config.template.yaml` → `config.yaml`)

```
config.template.yaml    checked into the repo, {{ENV_VAR}} placeholders + Redis markers
        │
        │  python3 render-config.py [--no-redis] [--dry-run] [--output <path>]
        ▼
config.yaml             rewritten on every render (gitignored)
        │
        ├─► LiteLLM container
        └─► multi-instance/generate-config.py
```

**Behavior of `render-config.py`:**

1. **Placeholder substitution**: `{{OPENROUTER_API_KEY}}` → value from `.env`.
2. **Provider filter**: if a required key is missing, the provider block (including the comment header) is removed. OVHcloud accepts an empty key.
3. **Redis blocks**: `# BEGIN REDIS ...`/`# END REDIS ...` regions (cache in litellm_settings, redis_* in router_settings) are only kept if `REDIS_HOST` is set and `--no-redis` was not passed; the marker lines themselves are always removed.
4. **OpenRouter-free fallback**: on/off depending on the key.
5. **Fallback validation**: orphaned keys AND orphaned chain targets are removed (fallbacks + context_window_fallbacks).
6. **Atomic writes**: backup of the PREVIOUS version as `config.yaml.bak.<timestamp>`, auto-pruned to the last 5.
7. **Single-deployment warning**: after the provider filter, warns if a chat model_name has only 1 deployment left (exceptions: `SINGLE_PROVIDER_ALLOWED`; provider-specific embeddings are intentionally exempt) — the ≥ 2-provider rule only applies to the template; missing keys can remove the redundancy at runtime.

**Triggered by:** manually, via Makefile dependencies (`docker-compose-up`, `k8s-apply`, `k8s-configmap`), after `find-shared-models.py --apply`, in CI.

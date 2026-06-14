# LiteLLM Free-Models Proxy

A [LiteLLM](https://github.com/BerriAI/litellm) proxy that aggregates **exclusively free LLM APIs** from 13 providers — with automatic load balancing, cooldown, and fallback chains. The same model (e.g. `gpt-oss-120b`) is covered by multiple providers to bypass individual free-tier rate limits.

![Tests](https://img.shields.io/badge/tests-56_passing-brightgreen)
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
- [Tests](#-tests)
- [Development](#-development)
- [Sync Workflow](#-sync-workflow)
- [Multi-Instance](#-multi-instance)
- [Contributing](#-contributing)
- [License](#-license)
- [Disclaimer](#-disclaimer)

---

## ✨ Features

- **13 providers, 24+ models** — OpenRouter, Cerebras, Groq, Cloudflare Workers AI, Google AI Studio, NVIDIA NIM, Mistral, Cohere, GitHub Models, OpenCode Zen, LLM7.io, HuggingFace Inference API, OVHcloud.
- **Automatic load balancing** — LiteLLM router distributes requests via `simple-shuffle` across all deployments of a given model.
- **Fallback chains** — each model has a prioritized list of fallbacks (e.g. `gpt-oss-120b` → `gpt-oss-20b` → `llama-3.3-70b-instruct`).
- **Anonymous OVHcloud tier** — the 13th provider runs **without an API key** (2 RPM/IP/model) and is ready to use out of the box.
- **Live pricing report** — `find-shared-models.py` shows hypothetical savings vs. paid-tier prices (LiteLLM reference DB).
- **Multi-instance setup** — Master + 2 Slaves in `multi-instance/` triple the effective rate limits.
- **Template pipeline** — `config.template.yaml` is the single source of truth; `render-config.py` renders `config.yaml` from it with `{{ENV_VAR}}` substitution and provider filtering.
- **56 unit tests** — Test suite for `render-config`, `find-shared-models`, `providers_config`, and the `multi-instance` generator.

---

## 🚀 Quickstart

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
                  │     Routing: simple-shuffle             │
   Client ──────► │     24 model_names, 70 deployments      │
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
   Client ──────► │   70 direct + 48 slave backends  │
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
| 5  | Google AI Studio        | API Key       | 2               | `GEMINI_API_KEY`                                | Gemini models |
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

Status: **24 model_names, 70 deployments** in the single-instance configuration (850+ lines `config.yaml`).

| Model                          | Provider Count | Main Providers                                       |
|--------------------------------|----------------|------------------------------------------------------|
| `gpt-oss-120b`                 | 7              | OpenRouter, Cerebras, Groq, Cloudflare, NVIDIA, OVHcloud, HuggingFace |
| `llama-3.3-70b-instruct`       | 6              | OpenRouter, Groq, Cloudflare, GitHub Models, OVHcloud, HuggingFace |
| `gpt-oss-20b`                  | 6              | OpenRouter, Cerebras, Groq, Cloudflare, OVHcloud, HuggingFace |
| `llama-3.1-8b`                 | 5              | Groq, Cloudflare, NVIDIA, GitHub Models, HuggingFace |
| `llama-4-scout`                | 4              | Groq, Cloudflare, GitHub Models, HuggingFace |
| `deepseek-v4-flash`            | 4              | OpenRouter, NVIDIA, OpenCode Zen, HuggingFace |
| `gemma-3-12b-it`               | 4              | Google AI, Cloudflare, OpenRouter, HuggingFace |
| `llama-4-maverick`             | 4              | Groq, OpenRouter, NVIDIA, HuggingFace |
| `gemma-4-26b-a4b-it`           | 3              | OpenRouter, Cloudflare, HuggingFace |
| `kimi-k2.6`                    | 3              | OpenRouter, Cloudflare, NVIDIA |
| `nemotron-3-120b`              | 3              | OpenRouter, Groq, NVIDIA |
| `nemotron-3-nano-30b`          | 3              | OpenRouter, NVIDIA, HuggingFace |
| `gemma-4-31b-it`               | 3              | OpenRouter, NVIDIA, HuggingFace |
| `nemotron-3-ultra`             | 3              | OpenRouter, OpenCode Zen, NVIDIA |
| `mistral-large`                | 2              | Mistral, GitHub Models |
| `command-r-plus`               | 2              | Cohere, GitHub Models |
| `qwen3-next-80b-a3b`           | 1              | OpenRouter |
| `big-pickle`                   | 1              | OpenCode Zen |
| `north-mini-code`              | 1              | OpenCode Zen |
| `openrouter-free`              | 1              | OpenRouter (catch-all) |
| `deepseek-r1-0528`             | 1              | LLM7.io |
| `qwen3-235b`                   | 1              | LLM7.io |
| `mistral-small-3.2`            | 1              | LLM7.io |
| `codestral-latest`             | 1              | LLM7.io |

Full deployment matrix and model variants: see [`AGENTS.md`](AGENTS.md) section 3.

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

`config.template.yaml` contains `{{ENV_VAR}}` placeholders (e.g. `{{OPENROUTER_API_KEY}}`) and a comment header per provider. `render-config.py` performs four steps:

1. **Substitution** — `{{ENV_VAR}}` → value from `.env`. Missing keys become empty strings.
2. **Block filter** — If a *required* key is missing, the entire provider block (including the comment header) is removed from `model_list`. OVHcloud is the exception and accepts an empty key.
3. **OpenRouter-free fallback** — If `OPENROUTER_API_KEY` is set, `openrouter-free` is appended to every fallback chain and to the catch-all `*`. If the key is missing, the entry is removed again (otherwise 401).
4. **Orphan cleanup** — Fallback entries that point to removed `model_names` are deleted.

Writes are atomic with a timestamped backup (`config.yaml.bak.<timestamp>`). Direct edits to `config.yaml` are **overwritten** on the next render — changes always belong in the template.

Related scripts:

- `find-shared-models.py` — Live provider sync + pricing report (see [Sync Workflow](#-sync-workflow))
- `providers_config.py` — Central provider definitions (env-var names, API format, RPM, API URLs)
- `multi-instance/generate-config.py` — Master/slave config generator

---

## 🧪 Tests

```bash
make test                # 56 unit tests, ~1s
```

The suite covers four modules:

- `tests/test_render_config.py` — substitution, block filter, OpenRouter-free logic
- `tests/test_find_shared_models.py` — overlap grouping, pricing cache
- `tests/test_providers_config.py` — provider metadata consistency
- `tests/test_multi_instance.py` — master/slave generator

The tests use only the Python standard library (`unittest`).

---

## 🛠️ Development

| Command                                                  | Purpose                                                |
|----------------------------------------------------------|--------------------------------------------------------|
| `make help`                                              | List all targets with a short description              |
| `make render-config`                                     | Render `config.template.yaml` → `config.yaml`          |
| `make render-config-dry`                                 | Dry run (no write)                                     |
| `make check-config`                                      | LiteLLM dry-run validation of `config.yaml`           |
| `make k8s-apply`                                         | Deploy everything to Kubernetes (namespace, secret, configmap, deployment, postgres) |
| `make k8s-delete`                                        | Remove everything from Kubernetes                      |
| `make k8s-logs`                                          | Stream pod logs                                        |
| `make docker-compose-up` / `make docker-compose-down`    | Control docker-compose                                 |
| `make docker-build` / `make docker-run`                  | Build / run the custom image                           |
| `make test`                                              | Run 56 unit tests                                      |
| `make lint` / `make format`                              | Run ruff linter / formatter                            |
| `make install-dev`                                       | Install dev dependencies and pre-commit hooks          |
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

1. Queries **all 13 providers live** (via the keys in `.env`; OVHcloud runs without a key).
2. Normalizes model names and groups by overlap (≥ 2 providers).
3. Compares hypothetical paid-tier prices from the LiteLLM reference DB (`https://models.litellm.ai/`, 24h cache in `.cache/`).
4. With `--apply`, writes new deployment blocks to `config.template.yaml` — existing comments, RPMs, and cost fields are preserved.

More detailed docs on `find-shared-models.py` and output formats: [`AGENTS.md`](AGENTS.md) section 10.

---

## 📦 Multi-Instance

The [`multi-instance/`](multi-instance/README.md) directory contains a complete master/slave setup:

- **Master** with 118 deployments (70 direct + 48 slave backends)
- **2 Slaves** with 70 deployments each under different API keys
- Dedicated `.env` files per instance (`master/.env`, `slave1/.env`, `slave2/.env`)
- Dedicated docker-compose and Kubernetes manifests (`multi-instance/k8s/`)
- Kustomize setup for declarative deployment

Prerequisite: **3 sets of API keys** (same providers, different accounts). Setup guide in [`multi-instance/README.md`](multi-instance/README.md).

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

# Multi-Instance LiteLLM Setup — 1 Master + 2 Slaves

Extends the [main setup](../README.md) to **3 independent LiteLLM instances** that work together to further work around rate limits.

> **When is this worth it?** LiteLLM can hold multiple deployments of the
> same provider with different keys **in a single instance** too — same
> 3× effect without a second config pipeline, three containers, and the
> master hop. The master/slave setup mainly pays off when the instances
> run on **separate hosts/egress IPs** (relevant for IP-based limits like
> OVHcloud's anonymous tier) or need to be operated separately.

## Architecture

```
                      ┌──────────────┐
  Client ──────────►  │   MASTER     │  Port 4000
                      │  (own        │
                      │   API keys)  │
                      └──────┬───────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │  Direct    │  │  SLAVE 1   │  │  SLAVE 2   │
     │ (own       │  │ Port 4001  │  │ Port 4002  │
     │  keys)     │  │ (own       │  │ (own       │
     │            │  │  keys)     │  │  keys)     │
     └────────────┘  └────────────┘  └────────────┘
```

**Master** (multi-instance/master/config.yaml):
- **99 direct deployments** using the master's API keys
- **72 slave deployments** (36 models × 2 slaves) that send HTTP requests to `slave1:4000` / `slave2:4000`
- → **171 deployments** total

**Each slave** (uses the base `config.yaml`):
- Runs with **its own API keys** (different accounts than the master and the other slaves)
- Proxies the request to the real providers (OpenRouter, Groq, etc.)

**Routing**: The master routes via `usage-based-routing-v2` across ALL 171 deployments — deployments with remaining `tpm`/`rpm` budget are preferred; usage is tracked cross-instance (including shared cooldowns) via the shared Redis. Once the direct deployments are exhausted, the master routes to a slave — which has its own keys and its own rate limits.

## Effect

| Model | Master Deployments (single instance) | Master Deployments (multi-instance) |
|---|---|---|
| `gpt-oss-120b` | 7 (providers) | **9** (7 direct + 2 slave routes) |
| `llama-3.3-70b-instruct` | 6 | **8** |
| Single provider | 1 | **3** (1 direct + 2 slave routes) |

Each slave route in turn fans out internally to all of that slave's provider deployments. Effectively, the provider rate limits are **tripled** (master + slave1 + slave2 with their own accounts each) — including for IP-based limits, given separate egress IPs.

## Prerequisites

- Docker & Docker Compose
- **3 sets of API keys** — one for the master, one each for slave1 and slave2
  - Same provider but **different accounts** = 3× more requests/minute

## Setup

```bash
cd multi-instance

# 1. Generate the master configuration
python3 generate-config.py

# 2. Create the project .env (Redis/Postgres passwords for Compose interpolation)
cp .env.example .env
# Set REDIS_PASSWORD and POSTGRES_PASSWORD (e.g. openssl rand -hex 16).
# Without these values, docker compose refuses to start (no silent
# default). Note: Compose reads ${VAR} ONLY from this project .env,
# never from the per-instance env_file files.

# 3. Create the per-instance .env files and fill in API keys
cp master/.env.example master/.env
cp slave1/.env.example slave1/.env
cp slave2/.env.example slave2/.env

# Now edit master/.env, slave1/.env, slave2/.env
# IMPORTANT: each instance needs DIFFERENT API keys!

# 4. Start
docker compose up -d

# 5. Test (against the master)
curl http://localhost:4000/health/readiness

curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $(grep LITELLM_MASTER_KEY master/.env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-oss-120b", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Ports

| Instance | Container Port | Host Port |
|---|---|---|
| Master | 4000 | 4000 |
| Slave 1 | 4000 | 4001 |
| Slave 2 | 4000 | 4002 |

## API Keys per Instance

Every `.env` file needs KEYS FROM DIFFERENT ACCOUNTS:

| Variable | Master | Slave 1 | Slave 2 |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Account A | Account B | Account C |
| `GROQ_API_KEY` | Account A | Account B | Account C |
| `CEREBRAS_API_KEY` | … | … | … |
| … | – | – | – |
| `LITELLM_MASTER_KEY` | `sk-master-xyz` | `sk-slave1-xyz` | `sk-slave2-xyz` |

The `SLAVE1_API_KEY`/`SLAVE2_API_KEY` values in the master must match the respective slave's `LITELLM_MASTER_KEY`.

## Updating the Configuration

## Kubernetes

The multi-instance setup can also run on Kubernetes. Master and slaves then run as separate pods, communicating via K8s service DNS (`http://litellm-slave-1:4000`).

### K8s Architecture

```
                      ┌──────────────┐
  Client ──────────►  │   MASTER     │  svc/litellm-master:4000
                      │  (own        │
                      │   keys)      │
                      └──────┬───────┘
                             │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
      ┌────────────┐  ┌────────────┐  ┌────────────┐
      │  Direct    │  │  SLAVE 1   │  │  SLAVE 2   │
      │ (own       │  │ svc/       │  │ svc/       │
      │  keys)     │  │ litellm-   │  │ litellm-   │
      │            │  │ slave-1    │  │ slave-2    │
      └────────────┘  └────────────┘  └────────────┘
```

Each slave has its own secret with **different API keys** (same secret variables, different values). The slaves share a ConfigMap (`litellm-slave-config`) with the base `config.yaml`.

### K8s Manifests

```
multi-instance/k8s/
├── namespace.yaml              # Namespace: litellm-free-models
├── kustomization.yaml          # Kustomize – all resources at once
├── master/
│   ├── configmap.yaml          # Generated (171 deployments)
│   ├── deployment.yaml         # Master pod
│   └── service.yaml            # ClusterIP: litellm-master
├── slave/
│   ├── configmap.yaml          # Generated (base config, 99 deployments)
│   ├── deployment.yaml         # Slave-1 + Slave-2 pods
│   └── service.yaml            # ClusterIP: litellm-slave-1, litellm-slave-2
└── secret.yaml.template        # Template for 3 secrets

# Redis (deployment/service) comes as a kustomize base from ../../k8s/redis/ –
# shared manifests with the single-instance setup, no copies.
# litellm-redis-secret is created via `make k8s-secret` in the repo root.
```

### Setup (K8s)

```bash
cd multi-instance

# 1. Generate configs (ConfigMaps for master + slaves)
python3 generate-config.py

# 2. Create secrets (separately per instance)
kubectl create secret generic litellm-master-secrets \
  --namespace litellm-free-models \
  --from-literal=LITELLM_MASTER_KEY="sk-master-..." \
  --from-literal=SLAVE1_API_KEY="sk-slave1-..." \
  --from-literal=SLAVE2_API_KEY="sk-slave2-..." \
  --from-literal=OPENROUTER_API_KEY="..." \
  --from-literal=GROQ_API_KEY="..." \
  ...

kubectl create secret generic litellm-slave1-secrets \
  --namespace litellm-free-models \
  --from-literal=LITELLM_MASTER_KEY="sk-slave1-..." \
  --from-literal=OPENROUTER_API_KEY="...different account..." \
  ...

kubectl create secret generic litellm-slave2-secrets \
  --namespace litellm-free-models \
  --from-literal=LITELLM_MASTER_KEY="sk-slave2-..." \
  --from-literal=OPENROUTER_API_KEY="...yet another account..." \
  ...

# 3. Deploy (Kustomize)
kubectl apply -k k8s/

# Alternative: individually
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/master/configmap.yaml
kubectl apply -f k8s/master/deployment.yaml
kubectl apply -f k8s/master/service.yaml
kubectl apply -f k8s/slave/configmap.yaml
kubectl apply -f k8s/slave/deployment.yaml
kubectl apply -f k8s/slave/service.yaml

# 4. Test
kubectl port-forward -n litellm-free-models svc/litellm-master 4000:4000
curl http://localhost:4000/health/readiness
```

**Important**: each slave needs ITS OWN secret with DIFFERENT API keys than the master and the other slaves. The `litellm-slave-config` ConfigMap is identical for all slaves (same model definitions).

### Updating the K8s Configuration

```bash
cd multi-instance
python3 generate-config.py   # regenerate ConfigMaps
kubectl apply -f k8s/master/configmap.yaml
kubectl apply -f k8s/slave/configmap.yaml
kubectl rollout restart deployment/litellm-master -n litellm-free-models
kubectl rollout restart deployment/litellm-slave-1 -n litellm-free-models
kubectl rollout restart deployment/litellm-slave-2 -n litellm-free-models
```

## Updating the Configuration (Docker)

```bash
cd multi-instance
python3 generate-config.py   # regenerate master/config.yaml
docker compose restart master
```

Slaves don't need to be restarted — they use the base `config.yaml` via a volume mount.

## File Structure

```
multi-instance/
├── .env.example              # Project .env: Redis/Postgres passwords (Compose interpolation)
├── master/
│   ├── config.yaml           # Docker config (99 base + 72 slave = 171)
│   └── .env.example          # Master keys + SLAVE1/2_API_KEY
├── slave1/
│   └── .env.example          # Slave-1 keys (different accounts)
├── slave2/
│   └── .env.example          # Slave-2 keys (different accounts)
├── k8s/                      # Kubernetes manifests
│   ├── namespace.yaml
│   ├── kustomization.yaml    # references ../../k8s/redis/ as a shared base
│   ├── master/
│   │   ├── configmap.yaml    # K8s ConfigMap (K8s DNS URLs, 171 dep.)
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── slave/
│   │   ├── configmap.yaml    # base config (K8s-indented, 69 dep.)
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   └── secret.yaml.template  # 3 secrets (master, slave1, slave2)
├── generate-config.py        # Generator (Docker + K8s ConfigMaps)
├── docker-compose.yaml       # Docker: master + 2 slaves + Redis + Postgres
└── README.md                 # This file
```

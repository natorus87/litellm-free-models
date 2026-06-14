# Multi-Instance LiteLLM Setup — 1 Master + 2 Slaves

Erweitert das [Haupt-Setup](../README.md) auf **3 eigenständige LiteLLM-Instanzen**, die zusammenarbeiten, um Rate-Limits weiter zu umgehen.

## Architektur

```
                      ┌──────────────┐
  Client ──────────►  │   MASTER     │  Port 4000
                      │  (eigene     │
                      │   API-Keys)  │
                      └──────┬───────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │  Direkt    │  │  SLAVE 1   │  │  SLAVE 2   │
     │ (eigene    │  │ Port 4001  │  │ Port 4002  │
     │  Keys)     │  │ (eigene    │  │ (eigene    │
     │            │  │  Keys)     │  │  Keys)     │
     └────────────┘  └────────────┘  └────────────┘
```

**Master** (mult‑instance/master/config.yaml):
- **70 direkte Deployments** mit den API-Keys des Masters
- **48 Slave-Deployments** (24 Modelle × 2 Slaves), die HTTP‑Requests an `slave1:4000` / `slave2:4000` senden
- → **118 Deployments** insgesamt

**Jeder Slave** (nutzt die base `config.yaml`):
- Läuft mit **eigenen API-Keys** (andere Accounts als Master und andere Slaves)
- Proxied die Anfrage an die echten Provider (OpenRouter, Groq, etc.)

**Routing**: Der Master routet per `simple-shuffle` über ALLE 118 Deployments. Fällt ein Deployment wegen Rate-Limit, geht's zum nächsten. Sind die direkten Deployments im Cooldown, routet der Master zu einem Slave – der hat eigene Keys und eigene Rate-Limits.

## Effekt

| Modell | Deployments (einfach) | Deployments (multi-instance) |
|---|---|---|
| `gpt-oss-120b` | 7 (Provider) | **21** (7 Provider + 2×7 Slave) |
| `llama-3.3-70b` | 6 | **18** |
| Single-Provider | 1 | **3** (1 direkt + 2 Slave) |

Die Rate-Limits werden **verdreifacht** (Master + Slave1 + Slave2), bei unterschiedlichen IPs sogar noch effektiver.

## Voraussetzungen

- Docker & Docker Compose
- **3 Sätze API-Keys** – einer für den Master, je einer für Slave1 und Slave2
  - Gleicher Provider, aber **unterschiedliche Accounts** = 3× mehr Requests/Minute

## Setup

```bash
cd multi-instance

# 1. Master-Konfiguration generieren
python3 generate-config.py

# 2. .env-Dateien anlegen und API-Keys eintragen
cp master/.env.example master/.env
cp slave1/.env.example slave1/.env
cp slave2/.env.example slave2/.env

# Jetzt master/.env, slave1/.env, slave2/.env editieren
# WICHTIG: Jede Instanz braucht ANDERE API-Keys!

# 3. Starten
docker compose up -d

# 4. Testen (gegen den Master)
curl http://localhost:4000/health/readiness

curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $(grep LITELLM_MASTER_KEY master/.env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-oss-120b", "messages": [{"role": "user", "content": "Hallo"}]}'
```

## Ports

| Instanz | Container-Port | Host-Port |
|---|---|---|
| Master | 4000 | 4000 |
| Slave 1 | 4000 | 4001 |
| Slave 2 | 4000 | 4002 |

## API-Keys pro Instanz

Jede `.env`-Datei braucht KEYS VON UNTERSCHIEDLICHEN ACCOUNTS:

| Variable | Master | Slave 1 | Slave 2 |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Account A | Account B | Account C |
| `GROQ_API_KEY` | Account A | Account B | Account C |
| `CEREBRAS_API_KEY` | … | … | … |
| … | – | – | – |
| `LITELLM_MASTER_KEY` | `sk-master-xyz` | `sk-slave1-xyz` | `sk-slave2-xyz` |

Die `SLAVE1_API_KEY`/`SLAVE2_API_KEY` im Master müssen mit dem `LITELLM_MASTER_KEY` des jeweiligen Slaves übereinstimmen.

## Konfiguration aktualisieren

## Kubernetes

Das Multi-Instance-Setup kann auch auf Kubernetes betrieben werden. Master und Slaves laufen dann als separate Pods, kommunizieren über K8s-Service-DNS (`http://litellm-slave-1:4000`).

### K8s-Architektur

```
                      ┌──────────────┐
  Client ──────────►  │   MASTER     │  svc/litellm-master:4000
                      │  (eigene     │
                      │   Keys)      │
                      └──────┬───────┘
                             │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
      ┌────────────┐  ┌────────────┐  ┌────────────┐
      │  Direkt    │  │  SLAVE 1   │  │  SLAVE 2   │
      │ (eigene    │  │ svc/       │  │ svc/       │
      │  Keys)     │  │ litellm-   │  │ litellm-   │
      │            │  │ slave-1    │  │ slave-2    │
      └────────────┘  └────────────┘  └────────────┘
```

Jeder Slave hat seinen eigenen Secret mit **unterschiedlichen API-Keys** (gleiche Secret-Variablen, andere Werte). Die Slaves teilen sich eine ConfigMap (`litellm-slave-config`) mit der base `config.yaml`.

### K8s-Manifeste

```
multi-instance/k8s/
├── namespace.yaml              # Namespace: litellm-free-models
├── kustomization.yaml          # Kustomize – alle Resourcen auf einmal
├── master/
│   ├── configmap.yaml          # Generiert (118 Deployments)
│   ├── deployment.yaml         # Master-Pod
│   └── service.yaml            # ClusterIP: litellm-master
├── slave/
│   ├── configmap.yaml          # Generiert (base config, 55 Deployments)
│   ├── deployment.yaml         # Slave-1 + Slave-2 Pods
│   └── service.yaml            # ClusterIP: litellm-slave-1, litellm-slave-2
└── secret.yaml.template        # Template für 3 Secrets
```

### Setup (K8s)

```bash
cd multi-instance

# 1. Configs generieren (ConfigMaps für Master + Slaves)
python3 generate-config.py

# 2. Secrets anlegen (getrennt pro Instanz)
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
  --from-literal=OPENROUTER_API_KEY="...anderer Account..." \
  ...

kubectl create secret generic litellm-slave2-secrets \
  --namespace litellm-free-models \
  --from-literal=LITELLM_MASTER_KEY="sk-slave2-..." \
  --from-literal=OPENROUTER_API_KEY="...wieder anderer Account..." \
  ...

# 3. Deployen (Kustomize)
kubectl apply -k k8s/

# Alternativ: einzeln
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/master/configmap.yaml
kubectl apply -f k8s/master/deployment.yaml
kubectl apply -f k8s/master/service.yaml
kubectl apply -f k8s/slave/configmap.yaml
kubectl apply -f k8s/slave/deployment.yaml
kubectl apply -f k8s/slave/service.yaml

# 4. Testen
kubectl port-forward -n litellm-free-models svc/litellm-master 4000:4000
curl http://localhost:4000/health/readiness
```

**Wichtig**: Jeder Slave braucht SEINEN Secret mit ANDEREN API-Keys als Master und die anderen Slaves. Die ConfigMap `litellm-slave-config` ist für alle Slaves identisch (gleiche Modell-Definitionen).

### K8s-Konfiguration aktualisieren

```bash
cd multi-instance
python3 generate-config.py   # ConfigMaps neu generieren
kubectl apply -f k8s/master/configmap.yaml
kubectl apply -f k8s/slave/configmap.yaml
kubectl rollout restart deployment/litellm-master -n litellm-free-models
kubectl rollout restart deployment/litellm-slave-1 -n litellm-free-models
kubectl rollout restart deployment/litellm-slave-2 -n litellm-free-models
```

## Konfiguration aktualisieren (Docker)

```bash
cd multi-instance
python3 generate-config.py   # master/config.yaml neu generieren
docker compose restart master
```

Slaves müssen nicht neugestartet werden – sie verwenden die base `config.yaml` per Volume-Mount.

## Dateistruktur

```
multi-instance/
├── master/
│   ├── config.yaml           # Docker-Config (70 base + 48 slave = 118)
│   └── .env.example          # Master-Keys + SLAVE1/2_API_KEY
├── slave1/
│   └── .env.example          # Slave-1-Keys (andere Accounts)
├── slave2/
│   └── .env.example          # Slave-2-Keys (andere Accounts)
├── k8s/                      # Kubernetes-Manifeste
│   ├── namespace.yaml
│   ├── kustomization.yaml
│   ├── master/
│   │   ├── configmap.yaml    # K8s-ConfigMap (K8s-DNS-URLs, 118 dep.)
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── slave/
│   │   ├── configmap.yaml    # Base config (K8s-indented, 70 dep.)
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   └── secret.yaml.template  # 3 Secrets (master, slave1, slave2)
├── generate-config.py        # Generator (Docker + K8s ConfigMaps)
├── docker-compose.yaml       # Docker: Master + 2 Slaves
└── README.md                 # Diese Datei
```
